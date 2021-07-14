# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from dataclasses import dataclass, field
from datetime import timedelta
from enum import auto
from typing import List, Optional

from ...core.contents import EventContent
from ...core.data import AutoStrEnum
from ...core.ids import MXC, EventId, RoomAlias, RoomId
from ...e2e import Algorithm


@dataclass
class Creation(EventContent):
    @dataclass
    class Predecessor:
        event_id: EventId
        room_id:  RoomId

    type    = "m.room.create"
    aliases = {"federate": "m.federate", "version": "room_version"}

    federate:    bool                  = True
    version:     str                   = "1"
    predecessor: Optional[Predecessor] = None


@dataclass
class Encryption(EventContent):
    type    = "m.room.encryption"
    aliases = {
        "sessions_max_age": "rotation_period_ms",
        "sessions_max_messages": "rotation_period_msgs",
    }

    sessions_max_age:      timedelta = timedelta(weeks=1)
    sessions_max_messages: int       = 100
    algorithm:             str       = Algorithm.megolm_v1.value


@dataclass
class Name(EventContent):
    type = "m.room.name"

    name: Optional[str] = None


@dataclass
class Topic(EventContent):
    type = "m.room.topic"

    topic: Optional[str] = None


@dataclass
class Avatar(EventContent):
    type = "m.room.avatar"

    # TODO: info
    url: Optional[MXC] = None


@dataclass
class CanonicalAlias(EventContent):
    type    = "m.room.canonical_alias"
    aliases = {"alternatives": "alt_aliases"}

    alias:        Optional[RoomAlias] = None
    alternatives: List[RoomAlias]     = field(default_factory=list)


@dataclass
class JoinRules(EventContent):
    class Rule(AutoStrEnum):
        public  = auto()
        invite  = auto()
        private = auto()

    type    = "m.room.join_rules"
    aliases = {"rule": "join_rule"}

    rule: Rule


@dataclass
class HistoryVisibility(EventContent):
    class Visibility(AutoStrEnum):
        invited        = auto()
        joined         = auto()
        shared         = auto()
        world_readable = auto()

    type    = "m.room.history_visibility"
    aliases = {"visibility": "history_visibility"}

    visibility: Visibility


@dataclass
class GuestAccess(EventContent):
    class Access(AutoStrEnum):
        can_join  = auto()
        forbidden = auto()

    type    = "m.room.guest_access"
    aliases = {"access": "guest_access"}

    access: Access


@dataclass
class PinnedEvents(EventContent):
    type = "m.room.pinned_events"

    pinned: List[EventId] = field(default_factory=list)


@dataclass
class Tombstone(EventContent):
    type    = "m.room.tombstone"
    aliases = {"server_message": "body"}

    server_message:   str
    replacement_room: RoomId


@dataclass
class ServerACL(EventContent):
    type = "m.room.server_acl"

    allow_ip_literals: bool      = True
    allow:             List[str] = field(default_factory=list)
    deny:              List[str] = field(default_factory=list)
