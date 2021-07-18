# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from pytest import mark

from mio.client import Client
from mio.rooms.contents.messages import Text
from mio.rooms.room import Room

pytestmark = mark.asyncio


async def test_send_to_lazy_encrypted_room(e2e_room: Room, bob: Client):
    await e2e_room.invite(bob.user_id)
    await bob.rooms.join(e2e_room.id)
    await e2e_room.client.sync.once()

    assert not e2e_room.state.all_users_loaded
    await e2e_room.timeline.send(Text("hi"))
    assert e2e_room.state.all_users_loaded
    assert len(e2e_room.state.users) == 2

    await bob.sync.once()
    assert isinstance(bob.rooms[e2e_room.id].timeline[-1].content, Text)
