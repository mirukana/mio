# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from datetime import datetime
from uuid import uuid4

from pytest import mark

from mio.client import Client
from mio.core.ids import RoomAlias
from mio.rooms.contents.messages import Text
from mio.rooms.contents.settings import CanonicalAlias
from mio.rooms.room import Room

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


async def test_receipts(room: Room):
    def without_dates(dct: dict) -> dict:
        new = {}
        for k, v in dct.items():
            if isinstance(v, tuple) and isinstance(v[1], datetime):
                new[k] = (v[0], "date")
            elif isinstance(v, dict):
                new[k] = without_dates(v)  # type: ignore
            elif isinstance(v, datetime):
                new[k] = "date"  # type: ignore
            else:
                new[k] = v
        return new

    client = room.client
    await room.send_receipt(room.timeline[-2].id)
    await client.sync.once()

    assert without_dates(room.receipts_by_user) == {
        client.user_id: {"m.read": (room.timeline[-2].id, "date")},
    }

    assert without_dates(room.receipts_by_event) == {
        room.timeline[-2].id: {"m.read": {client.user_id: "date"}},
    }

    # Update

    await room.send_receipt()
    await client.sync.once()

    user_in = {"m.read": (room.timeline[-1].id, "date")}
    assert without_dates(room.receipts_by_user) == {client.user_id: user_in}
    assert without_dates(room.state.me.receipts) == user_in

    event_in = {"m.read": {client.user_id: "date"}}
    assert without_dates(room.receipts_by_event) == {
        room.timeline[-1].id: event_in,
    }
    assert not room.timeline[-2].receipts
    assert without_dates(room.timeline[-1].receipts) == event_in


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
    assert await room.path.exists()
    await room.forget(leave_reason="bye")
    await room.client.sync.once()

    assert room.left
    assert room.id not in room.client.rooms
    assert room.id in room.client.rooms.forgotten
    assert not await room.path.parent.exists()

    await bob.sync.once()
    bob_members = bob.rooms[room.id].state.leavers
    assert bob_members[room.client.user_id].membership_reason == "bye"

    # Make sure events are not ignored if we rejoin or get invited again
    await room.client.rooms.join(room.id)
    await room.client.sync.once()
    assert room.id in room.client.rooms
    assert room.id not in room.client.rooms.forgotten
