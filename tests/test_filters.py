# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from pytest import mark

from mio.client import Client
from mio.filters import EventFilter, Filter

pytestmark = mark.asyncio


async def test_get_server_id(alice: Client):
    assert not alice._filters._data
    f1 = Filter()
    f2 = Filter(event_fields=["content.body"], presence=EventFilter(limit=1))

    id1_try1 = await alice._filters.get_server_id(f1)
    id1_try2 = await alice._filters.get_server_id(f1)
    assert len(alice._filters._data) == 1

    id2_try1 = await alice._filters.get_server_id(f2)
    id2_try2 = await alice._filters.get_server_id(f2)
    assert len(alice._filters._data) == 2

    assert id1_try1 == id1_try2
    assert id2_try1 == id2_try2
    assert id1_try1 != id2_try1
