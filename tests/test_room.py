from uuid import uuid4

from mio.client import Client
from mio.core.types import RoomAlias
from mio.rooms.contents.messages import Text
from mio.rooms.contents.settings import CanonicalAlias
from mio.rooms.room import Room
from pytest import mark

pytestmark = mark.asyncio


async def test_create_alias(room: Room):
    alias = RoomAlias(f"#{uuid4()}:localhost")
    await room.create_alias(alias)
    await room.state.send(CanonicalAlias(alias))
    await room.client.sync.once()
    assert room.state[CanonicalAlias].content.alias == alias


async def test_invite(room: Room, bob: Client):
    assert room.id not in bob.rooms
    await room.invite(bob.user_id)
    await bob.sync.once()
    assert room.id in bob.rooms.invited


async def test_leave(e2e_room: Room):
    await e2e_room.timeline.send(Text("make a session"))
    assert e2e_room.id in e2e_room.client._e2e.out_group_sessions

    await e2e_room.leave()
    await e2e_room.client.sync.once()
    assert e2e_room.left
    assert e2e_room.id not in e2e_room.client._e2e.out_group_sessions
