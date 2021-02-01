from enum import auto
from typing import Dict, List, Optional

from pydantic import AnyUrl, validator

from ..utils import AutoStrEnum
from . import (
    EmptyString, EventId, RoomAlias, RoomId, Sources, StateEvent, UserId,
)

# TODO: m.room.third_party_invite, prev_content


class Creation(StateEvent):
    type = "m.room.create"
    make = Sources(
        creator           = ("content", "creator"),
        federate          = ("content", "m.federate"),
        version           = ("content", "room_version"),
        previous_room_id  = ("content", "predecessor", "room_id"),
        previous_event_id = ("content", "predecessor", "event_id"),
    )

    state_key:         EmptyString
    creator:           UserId
    federate:          bool              = True
    version:           str               = "1"
    previous_room_id:  Optional[RoomId]  = None
    previous_event_id: Optional[EventId] = None


class Name(StateEvent):
    type = "m.room.name"
    make = Sources(name=("content", "name"))

    state_key: EmptyString
    name:      Optional[str]


class Topic(StateEvent):
    type = "m.room.topic"
    make = Sources(topic=("content", "topic"))

    state_key: EmptyString
    topic:     Optional[str]


class Avatar(StateEvent):
    type = "m.room.avatar"
    make = Sources(url=("content", "url"))

    state_key: EmptyString
    url:       Optional[AnyUrl]
    # TODO: info


class CanonicalAlias(StateEvent):
    type = "m.room.canonical_alias"
    make = Sources(
        alias        = ("content", "alias"),
        alternatives = ("content", "alt_aliases"),
    )

    state_key:    EmptyString
    alias:        RoomAlias
    alternatives: List[RoomAlias] = []


class JoinRules(StateEvent):
    class Rule(AutoStrEnum):
        public  = auto()
        knock   = auto()
        invite  = auto()
        private = auto()

    type = "m.room.join_rules"
    make = Sources(rule=("content", "join_rule"))

    state_key: EmptyString
    rule:      Rule


class HistoryVisibility(StateEvent):
    class Visibility(AutoStrEnum):
        invited        = auto()
        joined         = auto()
        shared         = auto()
        world_readable = auto()

    type = "m.room.history_visibility"
    make = Sources(visibility=("content", "history_visibility"))

    state_key:  EmptyString
    visibility: Visibility


class GuestAccess(StateEvent):
    class Access(AutoStrEnum):
        can_join  = auto()
        forbidden = auto()

    type = "m.room.guest_access"
    make = Sources(access=("content", "guest_access"))

    state_key: EmptyString
    access:    Access


class PinnedEvents(StateEvent):
    type = "m.room.pinned_events"
    make = Sources(pinned=("content", "pinned"))

    state_key: EmptyString
    pinned:    List[EventId] = []


class Tombstone(StateEvent):
    type = "m.room.tombstone"
    make = Sources(
        server_message   = ("content", "body"),
        replacement_room = ("content", "replacement_room"),
    )

    state_key:        EmptyString
    server_message:   str
    replacement_room: RoomId


class Member(StateEvent):
    class Membership(AutoStrEnum):
        invite = auto()
        join   = auto()
        knock  = auto()
        leave  = auto()
        ban    = auto()

    type = "m.room.member"
    make = Sources(
        avatar_url        = ("content", "avatar_url"),
        display_name      = ("content", "displayname"),
        membership        = ("content", "membership"),
        is_direct         = ("content", "is_direct"),
        third_party_name  = ("content", "third_party_invite", "display_name"),
        # invite_room_state = ("content", "unsigned", "invite_room_state"),
    )

    state_key:        UserId
    membership:       Membership
    avatar_url:       Optional[AnyUrl] = None
    display_name:     Optional[str]    = None
    is_direct:        bool             = False
    third_party_name: Optional[str]    = None
    # invite_room_state: List[StrippedState] = []  # TODO

    @property
    def left(self) -> bool:
        return self.membership in (self.Membership.leave, self.membership.ban)


class PowerLevels(StateEvent):
    type = "m.room.power_levels"
    make = Sources(
        invite         = ("content", "invite"),
        kick           = ("content", "kick"),
        ban            = ("content", "ban"),
        redact         = ("content", "redact"),
        events_default = ("content", "events_default"),
        state_default  = ("content", "state_default"),
        users_default  = ("content", "users_default"),
        events         = ("content", "events"),
        users          = ("content", "users"),
        notifications  = ("content", "notifications"),
    )

    state_key:      EmptyString
    invite:         int               = 50
    kick:           int               = 50
    ban:            int               = 50
    redact:         int               = 50
    events_default: int               = 0
    state_default:  int               = 50
    users_default:  int               = 0
    events:         Dict[str, int]    = {}
    users:          Dict[UserId, int] = {}
    notifications:  Dict[str, int]    = {"room": 50}

    @validator("notifications")
    def add_room_notif(cls, value):
        value.setdefault("room", 50)
        return value


class ServerACL(StateEvent):
    type = "m.room.server_acl"
    make = Sources(
        allow_ip_literals = ("content", "allow_ip_literals"),
        allow             = ("content", "allow"),
        deny              = ("content", "deny"),
    )

    state_key:         EmptyString
    allow_ip_literals: bool      = True
    allow:             List[str] = []
    deny:              List[str] = []
