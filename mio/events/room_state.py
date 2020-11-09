from enum import auto
from typing import List, Optional

from pydantic import AnyUrl

from ..utils import AutoStrEnum
from . import EventId, RoomAlias, RoomEvent, RoomId, Sources, UserId

# TODO: power levels, server ACL


class Creation(RoomEvent):
    type = "m.room.create"
    make = Sources(
        creator           = ("content", "creator"),
        federate          = ("content", "m.federate"),
        version           = ("content", "room_version"),
        previous_room_id  = ("content", "predecessor", "room_id"),
        previous_event_id = ("content", "predecessor", "event_id"),
    )

    creator:           UserId
    federate:          bool              = True
    version:           str               = "1"
    previous_room_id:  Optional[RoomId]  = None
    previous_event_id: Optional[EventId] = None


class Name(RoomEvent):
    type = "m.room.name"
    make = Sources(name=("content", "name"))

    name: Optional[str]


class Topic(RoomEvent):
    type = "m.room.topic"
    make = Sources(topic=("content", "topic"))

    topic: Optional[str]


class Avatar(RoomEvent):
    type = "m.room.avatar"
    make = Sources(url=("content", "url"))

    url: Optional[AnyUrl]
    # TODO: info


class CanonicalAlias(RoomEvent):
    type = "m.room.canonical_alias"
    make = Sources(
        alias        = ("content", "alias"),
        alternatives = ("content", "alt_aliases"),
    )

    alias:        RoomAlias
    alternatives: List[RoomAlias] = []


class JoinRules(RoomEvent):
    class Rule(AutoStrEnum):
        public  = auto()
        knock   = auto()
        invite  = auto()
        private = auto()

    type = "m.room.join_rules"
    make = Sources(rule=("content", "join_rule"))

    rule: Rule


class HistoryVisibility(RoomEvent):
    class Visibility(AutoStrEnum):
        invited        = auto()
        joined         = auto()
        shared         = auto()
        world_readable = auto()

    type = "m.room.history_visibility"
    make = Sources(visibility=("content", "history_visibility"))

    visibility: Visibility


class GuestAccess(RoomEvent):
    class Access(AutoStrEnum):
        can_join  = auto()
        forbidden = auto()

    type = "m.room.guest_access"
    make = Sources(access=("content", "guest_access"))

    access: Access


class PinnedEvents(RoomEvent):
    type = "m.room.pinned_events"
    make = Sources(pinned=("content", "pinned"))

    pinned: List[EventId] = []


class Tombstone(RoomEvent):
    type = "m.room.tombstone"
    make = Sources(
        server_message   = ("content", "body"),
        replacement_room = ("content", "replacement_room"),
    )

    server_message:   str
    replacement_room: RoomId


class Member(RoomEvent):
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

    membership:       Membership
    avatar_url:       Optional[AnyUrl] = None
    display_name:     Optional[str]    = None
    is_direct:        bool             = False
    third_party_name: Optional[str]    = None
    # invite_room_state: List[StrippedState] = []  # TODO
