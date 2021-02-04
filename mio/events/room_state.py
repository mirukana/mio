from enum import auto
from typing import Dict, List, Optional

from pydantic import AnyUrl, validator

from ..typing import EmptyString, EventId, RoomAlias, RoomId, UserId
from ..utils import AutoStrEnum, Const
from .base_events import StateEvent

# TODO: m.room.third_party_invite, prev_content


class Creation(StateEvent):
    class Matrix:
        creator           = ("content", "creator")
        federate          = ("content", "m.federate")
        version           = ("content", "room_version")
        previous_room_id  = ("content", "predecessor", "room_id")
        previous_event_id = ("content", "predecessor", "event_id")

    type = Const("m.room.create")

    state_key:         EmptyString
    creator:           UserId
    federate:          bool              = True
    version:           str               = "1"
    previous_room_id:  Optional[RoomId]  = None
    previous_event_id: Optional[EventId] = None


class Name(StateEvent):
    class Matrix:
        name = ("content", "name")

    type = Const("m.room.name")

    state_key: EmptyString
    name:      Optional[str]


class Topic(StateEvent):
    class Matrix:
        topic = ("content", "topic")

    type = Const("m.room.topic")

    state_key: EmptyString
    topic:     Optional[str]


class Avatar(StateEvent):
    class Matrix:
        url = ("content", "url")

    type = Const("m.room.avatar")

    # TODO: info
    state_key: EmptyString
    url:       Optional[AnyUrl]


class CanonicalAlias(StateEvent):
    class Matrix:
        alias        = ("content", "alias")
        alternatives = ("content", "alt_aliases")

    type = Const("m.room.canonical_alias")

    state_key:    EmptyString
    alias:        RoomAlias
    alternatives: List[RoomAlias] = []


class JoinRules(StateEvent):
    class Rule(AutoStrEnum):
        public  = auto()
        knock   = auto()
        invite  = auto()
        private = auto()

    class Matrix:
        rule = ("content", "join_rule")

    type = Const("m.room.join_rules")

    state_key: EmptyString
    rule:      Rule


class HistoryVisibility(StateEvent):
    class Visibility(AutoStrEnum):
        invited        = auto()
        joined         = auto()
        shared         = auto()
        world_readable = auto()

    class Matrix:
        visibility = ("content", "history_visibility")

    type = Const("m.room.history_visibility")

    state_key:  EmptyString
    visibility: Visibility


class GuestAccess(StateEvent):
    class Access(AutoStrEnum):
        can_join  = auto()
        forbidden = auto()

    class Matrix:
        access = ("content", "guest_access")

    type = Const("m.room.guest_access")

    state_key: EmptyString
    access:    Access


class PinnedEvents(StateEvent):
    class Matrix:
        pinned = ("content", "pinned")

    type = Const("m.room.pinned_events")

    state_key: EmptyString
    pinned:    List[EventId] = []


class Tombstone(StateEvent):
    class Matrix:
        server_message   = ("content", "body")
        replacement_room = ("content", "replacement_room")

    type = Const("m.room.tombstone")

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

    class Matrix:
        avatar_url        = ("content", "avatar_url")
        display_name      = ("content", "displayname")
        membership        = ("content", "membership")
        is_direct         = ("content", "is_direct")
        third_party_name  = ("content", "third_party_invite", "display_name")
        # invite_room_state = ("content", "unsigned", "invite_room_state"),

    type = Const("m.room.member")

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
    class Matrix:
        invite         = ("content", "invite")
        kick           = ("content", "kick")
        ban            = ("content", "ban")
        redact         = ("content", "redact")
        events_default = ("content", "events_default")
        state_default  = ("content", "state_default")
        users_default  = ("content", "users_default")
        events         = ("content", "events")
        users          = ("content", "users")
        notifications  = ("content", "notifications")

    type = Const("m.room.power_levels")

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
    class Matrix:
        allow_ip_literals = ("content", "allow_ip_literals")
        allow             = ("content", "allow")
        deny              = ("content", "deny")

    type = Const("m.room.server_acl")

    state_key:         EmptyString
    allow_ip_literals: bool      = True
    allow:             List[str] = []
    deny:              List[str] = []
