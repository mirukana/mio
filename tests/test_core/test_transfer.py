import asyncio
from io import StringIO
from typing import List

from mio.core.transfer import Transfer
from pytest import mark, raises

pytestmark = mark.asyncio


async def test_await():
    with raises(RuntimeError):
        await Transfer()

    async def coro():
        return "ok"

    assert await Transfer(task=coro()) == "ok"


async def test_anext_pause_stop():
    was_paused = []
    transfer   = Transfer(on_update=lambda t: was_paused.append(t.paused))
    assert not transfer.data and not transfer.paused

    with raises(asyncio.TimeoutError):
        await asyncio.wait_for(transfer.__anext__(), timeout=1)

    transfer.data = StringIO("x")
    await transfer.set_paused(True)
    assert was_paused[-1] is True

    with raises(asyncio.TimeoutError):
        await asyncio.wait_for(transfer.__anext__(), timeout=1)

    await transfer.set_paused(False)
    assert was_paused[-1] is False
    assert await transfer.__anext__() == "x"  # type: ignore

    await transfer.stop()
    with raises(StopAsyncIteration):
        assert await transfer.__anext__()


async def test_stop():
    was_stopped = []
    transfer    = Transfer(on_update=lambda t: was_stopped.append(t.stopped))

    await transfer.stop()
    assert transfer.stopped
    assert transfer.done_at
    assert was_stopped[-1] is True


async def test_stop_before_update():
    got: List[Transfer] = []
    transfer            = Transfer(size=64, on_update=got.append)

    assert transfer._updater.cancel()
    await transfer.stop()
    assert transfer.average_speed == 0

    calls_before_updater = len(got)
    transfer.read        = 32
    await transfer._update_loop()
    assert transfer.average_speed == 32
    assert len(got) > calls_before_updater

    calls_before_updater = len(got)
    transfer.on_update   = None
    await transfer._update_loop()
    assert transfer.average_speed == 32
    assert len(got) == calls_before_updater


async def test_average_speed_updater():
    transfer = Transfer(data=StringIO("x"))
    assert transfer.average_speed == 0

    async def wait_for_updater():
        while transfer.average_speed != 1:
            await asyncio.sleep(0.1)

    await transfer.__anext__()
    await asyncio.wait_for(wait_for_updater(), timeout=3)


async def test_size_left():
    assert Transfer().size_left is None
    assert Transfer(size=64).size_left == 64


async def test_percent_done():
    assert Transfer().percent_done is None

    transfer = Transfer(size=64)
    assert transfer.percent_done == 0.0
    transfer.read = 32
    assert transfer.percent_done == 50.0
    transfer.read = 64
    assert transfer.percent_done == 100.0


async def test_time_spent():
    assert Transfer().time_spent.seconds < 2


async def test_time_left():
    assert Transfer().time_left is None

    transfer = Transfer(size=100 ** 1000)
    assert transfer.average_speed == 0.0
    assert transfer.time_left is None  # ZeroDivisionError

    transfer.average_speed = 0.1
    assert transfer.time_left is None  # OverflowError

    transfer.size = transfer.average_speed = 64
    assert transfer.time_left.seconds == 1
