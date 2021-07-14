# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from pytest import mark, raises

from mio.client import Client
from mio.core.ids import MXC, UserId
from mio.net.errors import MatrixError
from mio.rooms.contents.settings import Name
from mio.rooms.room import Room

from ..conftest import ClientFactory

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


async def test_invited_by(alice: Client, bob: Client, room: Room):
    assert bob.user_id not in room.state.users
    await room.invite(bob.user_id)
    await alice.sync.once()
    assert room.state.invitees[bob.user_id].invited_by == alice.user_id


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


async def test_can_send_message(room: Room, bob: Client):
    # Can't send message because invitee
    await room.invite(bob.user_id)
    await room.client.sync.once()
    assert not room.state.invitees[bob.user_id].can_send_message()

    # Can send because joined
    await bob.rooms.join(room.id)
    await room.client.sync.once()
    assert room.state.members[bob.user_id].can_send_message()

    # Can't send because general power level too low
    await room.state.send(room.state.power_levels.but(messages_default=1))
    await room.client.sync.once()
    assert not room.state.members[bob.user_id].can_send_message()

    # Can send because this user's power level was raised
    await room.state.send(room.state.power_levels.but(users={bob.user_id: 2}))
    await room.client.sync.once()
    assert room.state.members[bob.user_id].can_send_message()


async def test_can_send_state(room: Room, bob: Client):
    # Can't send state because invitee
    await room.invite(bob.user_id)
    users = {**room.state.power_levels.users, bob.user_id: 50}
    await room.state.send(room.state.power_levels.but(users=users))
    await room.client.sync.once()
    assert not room.state.invitees[bob.user_id].can_send_state(Name)

    # Can send because joined
    await bob.rooms.join(room.id)
    await room.client.sync.once()
    assert room.state.members[bob.user_id].can_send_state(Name)

    # Can't send because power level too low
    events = {**room.state.power_levels.events, Name.type: 51}
    await room.state.send(room.state.power_levels.but(events=events))
    await room.client.sync.once()
    assert not room.state.members[bob.user_id].can_send_state(Name)

    # Can/can't send because of general state event minimum level
    assert "some_type" not in room.state.power_levels.events
    assert room.state.members[bob.user_id].can_send_state("some_type")
    await room.state.send(room.state.power_levels.but(state_default=60))
    await room.client.sync.once()
    assert not room.state.members[bob.user_id].can_send_state("some_type")


async def test_can_trigger_notification(room: Room, bob: Client):
    # Can't because invitee
    await room.invite(bob.user_id)
    users = {**room.state.power_levels.users, bob.user_id: 50}
    await room.state.send(room.state.power_levels.but(users=users))
    await room.client.sync.once()
    assert not room.state.invitees[bob.user_id].can_trigger_notification()

    # Can because joined
    await bob.rooms.join(room.id)
    await room.client.sync.once()
    assert room.state.members[bob.user_id].can_trigger_notification()
    assert "a" not in room.state.power_levels.notifications
    assert room.state.members[bob.user_id].can_trigger_notification("a")

    # Can't because power level too low
    await room.state.send(room.state.power_levels.but(notifications={"a": 51}))
    await room.client.sync.once()
    assert not room.state.members[bob.user_id].can_trigger_notification("a")


async def test_can_invite(room: Room, bob: Client):
    # Can't because invitee
    await room.invite(bob.user_id)
    users = {**room.state.power_levels.users, bob.user_id: 50}
    await room.state.send(room.state.power_levels.but(users=users))
    await room.client.sync.once()
    assert not room.state.invitees[bob.user_id].can_invite()

    # Can because joined
    await bob.rooms.join(room.id)
    await room.client.sync.once()
    assert room.state.members[bob.user_id].can_invite()
    assert room.state.members[bob.user_id].can_invite(UserId("@a:example.org"))

    # Can't because target is already joined
    assert not room.state.me.can_invite(bob.user_id)

    # Can't because target is banned
    await room.state.members[bob.user_id].ban()
    await room.client.sync.once()
    assert room.state.me.can_invite()
    assert not room.state.me.can_invite(bob.user_id)


async def test_can_affect_other_user(clients: ClientFactory):
    alice      = await clients.alice
    bob, carol = await clients.bob, await clients.carol

    for act in ("redact", "kick", "ban", "unban"):
        room_id = await alice.rooms.create(public=True, invitees=[bob.user_id])
        await alice.sync.once()
        room = alice.rooms[room_id]

        # Can't because invitee
        users = {alice.user_id: 100, bob.user_id: 50}
        await room.state.send(room.state.power_levels.but(users=users))
        await alice.sync.once()
        alice_func = getattr(room.state.me, f"can_{act}")
        bob_func   = getattr(room.state.users[bob.user_id], f"can_{act}")
        assert not bob_func()
        assert not bob_func(bob.user_id)

        # Can because joined
        await bob.rooms.join(room.id)
        await bob.sync.once()
        await alice.sync.once()
        assert bob_func()

        if act == "kick":
            # Can't because user not an invitee/member
            assert not alice_func("@unknown:example.org")

        elif act == "ban":
            # Must not already be banned
            await carol.rooms.join(room.id)
            await alice.sync.once()

            assert alice_func(carol.user_id)
            await room.state.users[carol.user_id].ban()
            await alice.sync.once()
            assert not alice_func(carol.user_id)

        elif act == "unban":
            await carol.rooms.join(room.id)
            await alice.sync.once()

            await room.state.members[carol.user_id].ban()
            await alice.sync.once()

            # Must actually be banned first
            assert alice_func(carol.user_id)
            await room.state.users[carol.user_id].unban()
            await alice.sync.once()
            assert not alice_func(carol.user_id)

        if act != "unban":
            # Can/can't because of sender and target power levels
            assert alice_func(bob.user_id)
            assert not bob_func(alice.user_id)

            # Can't because general level too low
            users = {alice.user_id: 48, bob.user_id: 49}
            await room.state.send(room.state.power_levels.but(users=users))
            await alice.sync.once()
            assert not bob_func(alice.user_id)

        if act in ("redact", "kick"):
            # Can always act on ourselves as long as we're joined
            assert bob_func(bob.user_id)
        else:
            assert not bob_func(bob.user_id)
