from pathlib import Path

from conftest import new_device_from
from mio.client import Client
from mio.core.errors import MatrixError
from pytest import mark, raises

pytestmark = mark.asyncio


async def test_logout(alice: Client):
    await alice.sync.once()
    await alice.auth.logout()

    with raises(MatrixError):
        await alice.sync.once()


async def test_logout_all(alice: Client, tmp_path: Path):
    alice2 = await new_device_from(alice, tmp_path)
    assert len(alice2.devices[alice.user_id]) == 2
    await alice.auth.logout_all_devices()

    with raises(MatrixError):
        await alice.sync.once()

    with raises(MatrixError):
        await alice2.sync.once()
