# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from mio.client import Client
from mio.core.ids import MXC
from mio.net.errors import MatrixError
from mio.rooms.room import Room
from pytest import mark, raises
from yarl import URL

pytestmark = mark.asyncio


async def test_profile_properties(alice: Client, room: Room):
    await alice.profile.set_name("Alice Margatroid")
    await alice.profile.set_avatar(MXC("mxc://localhost/1"))
    await alice.sync.once()

    assert room.state.me.display_name == alice.profile.name
    assert room.state.me.avatar_url == alice.profile.avatar


async def test_name_disambiguation(alice: Client, bob: Client, room: Room):
    state = room.state

    # Test what happens if member had no name (we can't do this by API)
    state.me.state.content.display_name = None
    assert state.me.unique_name == alice.user_id

    # No one shares the same name
    await alice.profile.set_name("Alice")
    await alice.sync.once()
    assert state.me.unique_name == "Alice"

    # Two people now share the same name
    await bob.profile.set_name("Alice")
    await bob.rooms.join(room.id)
    await alice.sync.once()
    assert state.me.unique_name == f"Alice ({alice.user_id})"
    assert state.members[bob.user_id].unique_name == f"Alice ({bob.user_id})"

    # The name collision disappears due to display name change
    await bob.profile.set_name("Fake Alice")
    await alice.sync.once()
    assert state.me.unique_name == "Alice"
    assert state.members[bob.user_id].unique_name == "Fake Alice"

    # The name collision disappears due to member leaving
    await bob.profile.set_name("Alice")
    await alice.sync.once()
    assert state.me.unique_name == f"Alice ({alice.user_id})"
    await state.members[bob.user_id].kick()
    await alice.sync.once()
    assert state.me.unique_name == "Alice"


async def test_power_level(room: Room):
    assert room.state.me.power_level == 100


async def test_inviter(alice: Client, bob: Client, room: Room):
    assert bob.user_id not in room.state.users
    await room.invite(bob.user_id)
    await alice.sync.once()
    assert room.state.invitees[bob.user_id].inviter == alice.user_id


async def test_join_leave_properties(alice: Client, room: Room):
    assert room.state.me.joined is True
    assert room.state.me.left is False
    await room.leave()
    await alice.sync.once()
    assert room.state.me.left is True


async def test_kick(alice: Client, bob: Client, room: Room):
    await bob.rooms.join(room.id)
    await alice.sync.once()
    await room.state.members[bob.user_id].kick("test")

    await alice.sync.once()
    assert bob.user_id not in room.state.members
    assert not room.state.leavers[bob.user_id].banned_by
    assert room.state.leavers[bob.user_id].kicked_by == alice.user_id
    assert room.state.leavers[bob.user_id].membership_reason == "test"


async def test_ban_unban(alice: Client, bob: Client, room: Room):
    await bob.rooms.join(room.id)
    await alice.sync.once()

    await room.state.members[bob.user_id].ban("test")
    await alice.sync.once()
    assert room.state.banned[bob.user_id].banned_by == alice.user_id
    assert room.state.banned[bob.user_id].membership_reason == "test"

    with raises(MatrixError):
        await bob.rooms.join(room.id)

    await room.state.banned[bob.user_id].unban("mistake")
    await alice.sync.once()
    assert room.state.leavers[bob.user_id].banned_by is None
    assert room.state.leavers[bob.user_id].membership_reason == "mistake"

    await bob.rooms.join(room.id)
