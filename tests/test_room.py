from uuid import uuid4

from mio.client import Client
from mio.core.types import RoomAlias
from mio.rooms.contents.messages import Text
from mio.rooms.contents.settings import CanonicalAlias
from mio.rooms.room import Room
from pytest import mark

pytestmark = mark.asyncio


async def test_typing(room: Room):
    assert not room.typing
    assert not room.state.members[room.client.user_id].typing

    await room.start_typing(timeout=600)
    await room.client.sync.once()
    assert room.typing == {room.client.user_id}
    assert room.state.members[room.client.user_id].typing

    await room.stop_typing()
    await room.client.sync.once()
    assert not room.typing
    assert not room.state.members[room.client.user_id].typing


async def test_create_alias(room: Room):
    alias = RoomAlias(f"#{uuid4()}:localhost")
    await room.create_alias(alias)
    await room.state.send(CanonicalAlias(alias))
    await room.client.sync.once()
    assert room.state[CanonicalAlias].content.alias == alias


async def test_invite(room: Room, bob: Client):
    assert room.id not in bob.rooms
    await room.invite(bob.user_id, reason="test")
    await bob.sync.once()
    assert room.id in bob.rooms.invited
    assert bob.rooms[room.id].state.me.membership_reason == "test"


async def test_leave(e2e_room: Room):
    await e2e_room.timeline.send(Text("make a session"))
    assert e2e_room.id in e2e_room.client.e2e._out_group_sessions

    await e2e_room.leave(reason="bye")
    await e2e_room.client.sync.once()
    assert e2e_room.left
    assert e2e_room.id not in e2e_room.client.e2e._out_group_sessions
    assert e2e_room.state.me.membership_reason == "bye"


async def test_forget(room: Room, bob: Client):
    # Server will destroy the room if there's only one user in who forgets it
    await bob.rooms.join(room.id)

    assert not room.left
    assert room.path.exists()
    await room.forget(leave_reason="bye")
    await room.client.sync.once()

    assert room.left
    assert room.id not in room.client.rooms
    assert room.id in room.client.rooms.forgotten
    assert not room.path.parent.exists()

    await bob.sync.once()
    bob_members = bob.rooms[room.id].state.leavers
    assert bob_members[room.client.user_id].membership_reason == "bye"

    # Make sure events are not ignored if we rejoin or get invited again
    await room.client.rooms.join(room.id)
    await room.client.sync.once()
    assert room.id in room.client.rooms
    assert room.id not in room.client.rooms.forgotten
