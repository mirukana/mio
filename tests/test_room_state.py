import asyncio
from uuid import uuid4

from mio.client import Client
from mio.core.types import RoomAlias
from mio.rooms.contents.settings import (
    Avatar, CanonicalAlias, Creation, Encryption, GuestAccess,
    HistoryVisibility, JoinRules, Name, PinnedEvents, PowerLevels, ServerACL,
    Tombstone, Topic,
)
from mio.rooms.contents.users import Member
from mio.rooms.room import Room
from pytest import mark, raises
from yarl import URL

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


async def test_settings_properties(alice: Client, room: Room):
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
        base_levels.but(events_default=-1),
        ServerACL(allow_ip_literals=False, allow=["*"]),
    ]

    await asyncio.gather(*[room.create_alias(a) for a in (alias, alt_alias)])
    await asyncio.gather(*[state.send(c) for c in to_send])  # type: ignore
    await state.send(Tombstone("dead", "!n:localhost"))
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
    assert state.power_levels == base_levels.but(events_default=-1)
    assert state.server_acl == ServerACL(allow_ip_literals=False, allow=["*"])
