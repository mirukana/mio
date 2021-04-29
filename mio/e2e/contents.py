# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar, Dict, List, Optional, Tuple
from uuid import uuid4

from ..core.contents import EventContent
from ..core.ids import RoomId
from . import MegolmAlgorithm, OlmAlgorithm

if TYPE_CHECKING:
    from ..rooms.events import TimelineEvent


@dataclass
class Olm(EventContent):
    @dataclass
    class Cipher:
        class Type(Enum):
            prekey = 0
            normal = 1

        type: Type
        body: str

    type    = "m.room.encrypted"
    aliases = {"sender_curve25519": "sender_key"}

    algorithm: ClassVar[str] = OlmAlgorithm.olm_v1.value

    sender_curve25519: str
    ciphertext:        Dict[str, Cipher]  # {recipient_curve_25519: Cipher}

    @classmethod
    def matches(cls, event: Dict[str, Any]) -> bool:
        algo = event.get("content", {}).get("algorithm")
        return super().matches(event) and cls.algorithm == algo


@dataclass
class Megolm(EventContent):
    type    = "m.room.encrypted"
    aliases = {"sender_curve25519": "sender_key"}

    algorithm: ClassVar[str] = MegolmAlgorithm.megolm_v1.value

    sender_curve25519: str
    ciphertext:        str
    device_id:         str
    session_id:        str

    @classmethod
    def matches(cls, event: Dict[str, Any]) -> bool:
        algo = event.get("content", {}).get("algorithm")
        return super().matches(event) and cls.algorithm == algo


@dataclass
class GroupSessionInfo(EventContent):
    type = "m.room_key"

    algorithm:   MegolmAlgorithm
    room_id:     RoomId
    session_id:  str
    session_key: str


@dataclass
class GroupSessionRequestBase(EventContent):
    type = "m.room_key_request"

    action: ClassVar[Optional[str]] = None

    request_id:           str
    requesting_device_id: str


    @classmethod
    def matches(cls, event: Dict[str, Any]) -> bool:
        if not cls.action:
            return False

        action = event.get("content", {}).get("action")
        return super().matches(event) and cls.action == action


@dataclass
class GroupSessionRequest(GroupSessionRequestBase):
    action  = "request"
    aliases = {
        "algorithm":                  ("body", "algorithm"),
        "room_id":                    ("body", "room_id"),
        "session_creator_curve25519": ("body", "sender_key"),
        "session_id":                 ("body", "session_id"),
    }

    algorithm:                  MegolmAlgorithm
    room_id:                    RoomId
    session_creator_curve25519: str
    session_id:                 str


    @classmethod
    def from_megolm(
        cls, event: "TimelineEvent[Megolm]",
    ) -> "GroupSessionRequest":
        return cls(
            request_id                 = str(uuid4()),
            requesting_device_id       = event.room.client.device_id,
            algorithm                  = MegolmAlgorithm.megolm_v1,
            room_id                    = event.room.id,
            session_creator_curve25519 = event.content.sender_curve25519,
            session_id                 = event.content.session_id,
        )


    @property
    def compare_key(self) -> Tuple[RoomId, str, str]:
        return (self.room_id, self.session_creator_curve25519, self.session_id)


    @property
    def cancellation(self) -> "CancelGroupSessionRequest":
        args = (self.request_id, self.requesting_device_id)
        return CancelGroupSessionRequest(*args)


    def is_for_megolm(self, event: "TimelineEvent[Megolm]") -> bool:
        event_curve = event.content.sender_curve25519
        event_key   = (event.room.id, event_curve, event.content.session_id)
        return self.compare_key == event_key


@dataclass
class CancelGroupSessionRequest(GroupSessionRequestBase):
    action = "request_cancellation"


@dataclass
class ForwardedGroupSessionInfo(EventContent):
    type  = "m.room.forwarded_room_key"
    alias = {
        "session_creator_curve25519": "sender_key",
        "creator_supposed_ed25519":   "sender_claimed_ed25519_key",
        "curve25519_forward_chain":   "forwarding_curve25519_key_chain",
    }

    algorithm:                  MegolmAlgorithm
    room_id:                    RoomId
    session_creator_curve25519: str
    creator_supposed_ed25519:   str
    session_id:                 str
    session_key:                str
    curve25519_forward_chain:   List[str]

    @property
    def compare_key(self) -> Tuple[RoomId, str, str]:
        return (self.room_id, self.session_creator_curve25519, self.session_id)


@dataclass
class Dummy(EventContent):
    type = "m.dummy"
