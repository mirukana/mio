from dataclasses import dataclass, field
from enum import auto
from typing import Dict, List, Optional

from ..typing import EventId, MxcUri, RoomAlias, RoomId, UserId
from ..utils import AutoStrEnum
from .base_events import Content

# TODO: m.room.third_party_invite


@dataclass
class Creation(Content):
    type    = "m.room.create"
    aliases = {
        "federate": "m.federate",
        "version": "room_version",
        "previous_room_id":  ("predecessor", "room_id"),
        "previous_event_id": ("predecessor", "event_id"),
    }

    creator:           UserId
    federate:          bool              = True
    version:           str               = "1"
    previous_room_id:  Optional[RoomId]  = None
    previous_event_id: Optional[EventId] = None


@dataclass
class Name(Content):
    type = "m.room.name"

    name: Optional[str] = None


@dataclass
class Topic(Content):
    type = "m.room.topic"

    topic: Optional[str] = None


@dataclass
class Avatar(Content):
    type = "m.room.avatar"

    # TODO: info
    url: Optional[MxcUri] = None


@dataclass
class CanonicalAlias(Content):
    type    = "m.room.canonical_alias"
    aliases = {"alternatives": "alt_aliases"}

    alias:        Optional[RoomAlias] = None
    alternatives: List[RoomAlias]     = field(default_factory=list)


@dataclass
class JoinRules(Content):
    class Rule(AutoStrEnum):
        public  = auto()
        knock   = auto()
        invite  = auto()
        private = auto()

    type    = "m.room.join_rules"
    aliases = {"rule": "join_rule"}

    rule: Rule


@dataclass
class HistoryVisibility(Content):
    class Visibility(AutoStrEnum):
        invited        = auto()
        joined         = auto()
        shared         = auto()
        world_readable = auto()

    type    = "m.room.history_visibility"
    aliases = {"visibility": "history_visibility"}

    visibility: Visibility


@dataclass
class GuestAccess(Content):
    class Access(AutoStrEnum):
        can_join  = auto()
        forbidden = auto()

    type    = "m.room.guest_access"
    aliases = {"access": "guest_access"}

    access: Access


@dataclass
class PinnedEvents(Content):
    type = "m.room.pinned_events"

    pinned: List[EventId]


@dataclass
class Tombstone(Content):
    type    = "m.room.tombstone"
    aliases = {"server_message": "body"}

    server_message:   str
    replacement_room: RoomId


@dataclass
class Member(Content):
    class Membership(AutoStrEnum):
        invite = auto()
        join   = auto()
        knock  = auto()
        leave  = auto()
        ban    = auto()

    type    = "m.room.member"
    aliases = {
        "display_name": "displayname",
        "third_party_name": ("third_party_invite", "display_name"),
        # "invite_room_state": ("unsigned", "invite_room_state"),  # TODO
    }

    membership:       Membership
    avatar_url:       Optional[MxcUri] = None
    display_name:     Optional[str]    = None
    is_direct:        bool             = False
    third_party_name: Optional[str]    = None
    # invite_room_state: List[StrippedState] = []  # TODO

    @property
    def left(self) -> bool:
        return self.membership in (self.Membership.leave, self.membership.ban)


@dataclass
class PowerLevels(Content):
    type = "m.room.power_levels"

    invite:         int               = 50
    kick:           int               = 50
    ban:            int               = 50
    redact:         int               = 50
    events_default: int               = 0
    state_default:  int               = 50
    users_default:  int               = 0
    events:         Dict[str, int]    = field(default_factory=dict)
    users:          Dict[UserId, int] = field(default_factory=dict)
    notifications:  Dict[str, int]    = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.notifications.setdefault("room", 50)


@dataclass
class ServerACL(Content):
    type = "m.room.server_acl"

    allow_ip_literals: bool      = True
    allow:             List[str] = field(default_factory=list)
    deny:              List[str] = field(default_factory=list)
