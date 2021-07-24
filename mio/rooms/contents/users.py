# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from dataclasses import dataclass, field
from enum import auto
from typing import Dict, Optional, Type

from ...core.contents import EventContent, EventContentType, str_type
from ...core.data import AutoStrEnum
from ...core.ids import MXC, UserId
from .messages import Message
from .settings import (
    Avatar, CanonicalAlias, Encryption, HistoryVisibility, Name, ServerACL,
    Tombstone,
)

# TODO: m.room.third_party_invite


@dataclass
class Member(EventContent):
    class Kind(AutoStrEnum):
        invite = auto()
        join   = auto()
        leave  = auto()
        ban    = auto()

    type    = "m.room.member"
    aliases = {
        "display_name": "displayname",
        "third_party_name": ("third_party_invite", "display_name"),
        # "invite_room_state": ("unsigned", "invite_room_state"),  # TODO
    }

    membership:       Kind
    reason:           Optional[str] = None
    display_name:     Optional[str] = None
    avatar_url:       Optional[MXC] = None
    is_direct:        bool          = False
    third_party_name: Optional[str] = None
    # invite_room_state: List[StrippedState] = []  # TODO

    @property
    def absent(self) -> bool:
        return self.membership in (self.Kind.leave, self.Kind.ban)

    @property
    def _redacted(self) -> "Member":
        return type(self)(membership=self.membership)


@dataclass
class PowerLevels(EventContent):
    type    = "m.room.power_levels"
    aliases = {"messages_default": "events_default"}

    invite: int = 50
    redact: int = 50
    kick:   int = 50
    ban:    int = 50

    users_default:    int = 0
    messages_default: int = 0
    state_default:    int = 50

    users:         Dict[UserId, int] = field(default_factory=dict)
    events:        Dict[str, int]    = field(default_factory=dict)
    notifications: Dict[str, int]    = field(default_factory=dict)

    def __post_init__(self) -> None:
        content: Type[EventContent]

        for content in (
            PowerLevels, HistoryVisibility, Tombstone, ServerACL, Encryption,
        ):
            assert content.type
            self.events.setdefault(content.type, 100)

        for content in (Name, CanonicalAlias, Avatar):
            assert content.type
            self.events.setdefault(content.type, 50)

        self.notifications.setdefault("room", 50)

    def user_level(self, user_id: UserId) -> int:
        return self.users.get(user_id, self.users_default)

    def message_min_level(self, event_type: EventContentType = Message) -> int:
        return self.events.get(str_type(event_type), self.messages_default)

    def state_min_level(self, event_type: EventContentType) -> int:
        return self.events.get(str_type(event_type), self.state_default)

    def notification_min_level(self, kind: str) -> int:
        return self.notifications.get(kind, 50)

    @property
    def _redacted(self) -> "PowerLevels":
        return self.but(invite=50, notifications={"room": 50})
