# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

import asyncio
import re
from typing import Optional, Pattern, Union
from uuid import uuid4

from pytest import mark, raises
from yarl import URL

from mio.client import Client
from mio.core.ids import RoomAlias, RoomId
from mio.filters import LAZY_LOAD, Filter
from mio.rooms.contents.settings import (
    Avatar, CanonicalAlias, Creation, Encryption, GuestAccess,
    HistoryVisibility, JoinRules, Name, PinnedEvents, ServerACL, Tombstone,
    Topic,
)
from mio.rooms.contents.users import Member, PowerLevels
from mio.rooms.events import StateEvent
from mio.rooms.room import Room

from ..conftest import ClientFactory

pytestmark = mark.asyncio


async def test_indexing(room: Room):
    creation = room.state._data["m.room.create", ""]
    assert isinstance(creation.content, Creation)

    assert room.state["m.room.create"] == creation
    assert room.state["m.room.create", ""] == creation
    assert room.state[Creation] == creation
    assert room.state[Creation, ""] == creation

    us = room.state._data["m.room.member", room.client.user_id]
    assert isinstance(us.content, Member)
    assert us.state_key == room.client.user_id

    assert room.state["m.room.member", room.client.user_id] == us
    assert room.state[Member, room.client.user_id] == us

    with raises(KeyError):
        room.state["m.room.member"]

    with raises(KeyError):
        room.state[Member]


async def test_settings_properties(room: Room):
    state       = room.state
    base_levels = PowerLevels(users={room.client.user_id: 100})

    assert state.creator == room.client.user_id
    assert state.federated is True
    assert state.version == state[Creation].content.version
    assert state.predecessor is None
    assert state.encryption is None
    assert state.name is None
    assert state.topic is None
    assert state.avatar is None
    assert state.alias is None
    assert state.alt_aliases == []
    assert state.join_rule is JoinRules.Rule.public
    assert state.history_visibility is HistoryVisibility.Visibility.shared
    assert state.guest_access is GuestAccess.Access.forbidden
    assert state.pinned_events == []
    assert state.tombstone is None
    assert state.power_levels == base_levels
    assert state.server_acl == ServerACL(allow=["*"])

    alias       = RoomAlias(f"#{uuid4()}:localhost")
    alt_alias   = RoomAlias(f"#{uuid4()}:localhost")
    to_send     = [
        Encryption(),
        Name("example"),
        Topic("blah"),
        Avatar(URL("mxc://exam.ple/1")),
        CanonicalAlias(alias, [alt_alias]),
        JoinRules(JoinRules.Rule.private),
        HistoryVisibility(HistoryVisibility.Visibility.invited),
        GuestAccess(GuestAccess.Access.can_join),
        PinnedEvents(["$a:localhost"]),  # type: ignore
        base_levels.but(messages_default=-1),
        ServerACL(allow_ip_literals=False, allow=["*"]),
    ]

    await asyncio.gather(*[room.create_alias(a) for a in (alias, alt_alias)])
    await asyncio.gather(*[state.send(c) for c in to_send])
    await state.send(Tombstone("dead", RoomId("!n:localhost")))
    await room.client.sync.once()

    assert state.encryption == Encryption()
    assert state.name == "example"
    assert state.topic == "blah"
    assert state.avatar == URL("mxc://exam.ple/1")
    assert state.alias == alias
    assert state.alt_aliases == [alt_alias]
    assert state.join_rule is JoinRules.Rule.private
    visib = HistoryVisibility.Visibility.invited  # type: ignore
    assert state.history_visibility is visib
    assert state.guest_access is GuestAccess.Access.can_join
    assert state.pinned_events == ["$a:localhost"]
    assert state.tombstone == Tombstone("dead", "!n:localhost")
    assert state.power_levels == base_levels.but(messages_default=-1)
    assert state.server_acl == ServerACL(allow_ip_literals=False, allow=["*"])


async def test_user_dicts(alice: Client, room: Room, bob: Client):
    state = room.state
    assert set(state.users) == {alice.user_id}
    assert set(state.members) == {alice.user_id}
    assert not state.invitees and not state.leavers and not state.banned

    await room.invite(bob.user_id)
    await alice.sync.once()
    assert set(state.users) == {alice.user_id, bob.user_id}
    assert set(state.members) == {alice.user_id}
    assert set(state.invitees) == {bob.user_id}
    assert not state.leavers and not state.banned

    await state.invitees[bob.user_id].kick()
    await alice.sync.once()
    assert set(state.users) == {alice.user_id, bob.user_id}
    assert set(state.members) == {alice.user_id}
    assert set(state.leavers) == {bob.user_id}
    assert not state.invitees and not state.banned

    await state.leavers[bob.user_id].ban()
    await alice.sync.once()
    assert set(state.users) == {alice.user_id, bob.user_id}
    assert set(state.members) == {alice.user_id}
    assert set(state.banned) == {bob.user_id}
    assert not state.invitees and not state.leavers


async def _display_name(clients: ClientFactory, filter: Optional[Filter]):
    # TODO: test with lazy load room fields

    alice   = await clients.alice
    room_id = await alice.rooms.create(public=True)
    await alice.sync.once(filter=filter)
    room  = alice.rooms[room_id]


    async def check_name(wanted: Union[str, Pattern]):
        # Don't use lazy loading, names order will be inconsistent
        await alice.sync.once(filter=filter)

        if isinstance(wanted, str):
            return wanted == room.state.display_name

        return wanted.match(room.state.display_name)

    # 1 member (us)

    assert len(room.state.users) == 1
    assert room.state.display_name == "Empty Room"

    # 2 members

    bob = await clients.bob
    await bob.profile.set_name("Bob")
    await bob.rooms.join(room.id)
    await check_name("Bob")

    # 3 members

    carol = await clients.carol
    await carol.profile.set_name("Carol")
    await carol.rooms.join(room.id)
    await check_name("Bob and Carol")

    # 4 members

    dave = await clients.dave
    await dave.profile.set_name("Dave")
    await dave.rooms.join(room.id)
    await check_name("Bob, Carol and Dave")

    # 5 joined, 1 invited - more than 6 members total

    erin = await clients.erin
    await erin.profile.set_name("Erin")
    await erin.rooms.join(room.id)

    frank = await clients.frank
    await frank.profile.set_name("Frank")
    await frank.rooms.join(room.id)

    mallory = await clients.mallory
    await mallory.profile.set_name("Frank")
    await room.invite(mallory.user_id)

    fr1 = frank.user_id
    fr2 = mallory.user_id
    await check_name(f"Bob, Carol, Dave, Erin, Frank ({fr1}) and 1 more")

    # 4 joined, 1 invited, 1 left and display name conflict

    await bob.sync.once(filter=filter)
    await bob.rooms[room.id].leave()
    await check_name(f"Carol, Dave, Erin, Frank ({fr1}) and Frank ({fr2})")

    # 1 joined (us), 1 invited, 5 left and no more display name conflict

    for client in (carol, dave, erin, frank):
        await room.state.users[client.user_id].kick()

    await check_name("Frank")

    # 1 joined (us), 5 left, 1 banned

    await alice.sync.once(filter=filter)
    await room.state.users[mallory.user_id].ban()
    await check_name(re.compile(
        r"^Empty Room \(had @.+, @.+, @.+, @.+ and @.+\)$",
    ))

    # 1 joined (us), 6 banned (FIXME: display "and more" for empty rooms)

    for client in (bob, carol, dave, erin, frank):
        await room.state.users[client.user_id].ban()

    await check_name(re.compile(
        r"^Empty Room \(had @.+, @.+, @.+, @.+ and @.+\)$",
    ))

    # Room with an alias

    alias = RoomAlias(f"#{uuid4()}:localhost")
    await room.create_alias(alias)
    await room.state.send(CanonicalAlias(alias))
    await check_name(alias)

    # Room with an explicit name

    await room.state.send(Name("Forest of Magic"))
    await check_name("Forest of Magic")


async def test_display_name_full_sync(clients: ClientFactory):
    await _display_name(clients, filter=None)


async def test_display_name_lazy_sync(clients: ClientFactory):
    await _display_name(clients, filter=LAZY_LOAD)


async def test_load_all_users(alice: Client, bob: Client, room: Room):
    await room.invite(bob.user_id)

    # Initial state when invited, no users manually loaded

    await bob.sync.once()
    assert not bob.rooms[room.id].state.all_users_loaded

    # Loading users while invited (not kept up to date by server)

    got = []
    cb  = lambda r, e: got.extend([type(r), type(e.content)])  # noqa
    bob.rooms.callbacks[StateEvent].append(cb)

    assert await bob.rooms[room.id].state.load_all_users()
    assert set(bob.rooms[room.id].state.users) == {alice.user_id, bob.user_id}
    assert not bob.rooms[room.id].state.all_users_loaded

    assert got == [Room, Member, Room, Member]

    # Loading users while joined

    await bob.rooms.join(room.id)
    await bob.sync.once()
    assert not bob.rooms[room.id].state.all_users_loaded
    assert await bob.rooms[room.id].state.load_all_users()
    assert bob.rooms[room.id].state.all_users_loaded
    assert not await bob.rooms[room.id].state.load_all_users()
    assert set(bob.rooms[room.id].state.users) == {alice.user_id, bob.user_id}
