# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from dataclasses import dataclass

from mio.account_data.events import AccountDataEvent
from mio.client import Client
from mio.core.callbacks import CallbackGroup
from mio.core.contents import EventContent
from pytest import mark

pytestmark = mark.asyncio


async def test_sending_receiving(alice: Client):
    @dataclass
    class Test(EventContent):
        type = "mio.test"
        foo: int

    got       = []
    group_got = []

    class TestCbGroup(CallbackGroup):
        def on_test(self, _, event: AccountDataEvent[Test]) -> None:
            group_got.append(event)

    alice.account_data.callbacks[Test].append(lambda self, ev: got.append(ev))
    alice.account_data.callback_groups.append(TestCbGroup())

    assert Test not in alice.account_data
    assert "mio.test" not in alice.account_data

    await alice.account_data.send(Test(1))
    await alice.sync.once()

    assert len(got) == len(group_got) == 1
    assert got[0].content == group_got[0].content == Test(1)
    assert alice.account_data[Test].content == Test(1)
    assert alice.account_data["mio.test"].content == Test(1)
