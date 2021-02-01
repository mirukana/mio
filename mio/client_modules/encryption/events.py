from datetime import timedelta
from enum import Enum
from typing import Any, ClassVar, Dict, Optional

from pydantic import BaseModel

from ...events import (
    EmptyString, Event, RoomEvent, RoomId, Sources, StateEvent, ToDeviceEvent,
    UserId,
)
from .errors import DecryptionError


class EncryptionSettings(StateEvent):
    type = "m.room.encryption"
    make = Sources(
        sessions_max_age      = ("content", "rotation_period_ms"),
        sessions_max_messages = ("content", "rotation_period_msgs"),
        algorithm             = ("content", "algorithm"),
    )

    state_key:             EmptyString
    sessions_max_age:      timedelta = timedelta(weeks=1)
    sessions_max_messages: int       = 100
    algorithm:             str       = "m.megolm.v1.aes-sha2"


class Olm(Event):
    class Cipher(BaseModel):
        class Type(Enum):
            prekey = 0
            normal = 1

        type: Type
        body: str

    type = "m.room.encrypted"
    make = Sources(
        algorithm         = ("content", "algorithm"),
        sender            = "sender",
        sender_curve25519 = ("content", "sender_key"),
        ciphertext        = ("content", "ciphertext"),
    )

    algorithm: ClassVar[str] = "m.olm.v1.curve25519-aes-sha2"

    sender:            UserId
    sender_curve25519: str
    ciphertext:        Dict[str, Cipher]  # {recipient_curve_25519: Cipher}
    decryption_error:  Optional[DecryptionError] = None

    @classmethod
    def matches_event(cls, event: Dict[str, Any]) -> bool:
        algo = event.get("content", {}).get("algorithm")
        return cls.type == event.get("type") and cls.algorithm == algo

    @property
    def matrix(self) -> Dict[str, Any]:
        event = super().matrix
        # make sure this is always included
        event["content"]["algorithm"] = self.algorithm
        return event


class Megolm(RoomEvent):
    type = "m.room.encrypted"
    make = Sources(
        algorithm         = ("content", "algorithm"),
        sender_curve25519 = ("content", "sender_key"),
        ciphertext        = ("content", "ciphertext"),
        device_id         = ("content", "device_id"),
        session_id        = ("content", "session_id"),
    )

    algorithm: ClassVar[str] = "m.megolm.v1.aes-sha2"

    sender_curve25519: str
    ciphertext:        str
    device_id:         str
    session_id:        str
    decryption_error:  Optional[DecryptionError] = None

    @classmethod
    def matches_event(cls, event: Dict[str, Any]) -> bool:
        algo = event.get("content", {}).get("algorithm")
        return cls.type == event.get("type") and cls.algorithm == algo

    @property
    def matrix(self) -> Dict[str, Any]:
        event = super().matrix
        # make sure this is always included
        event["content"]["algorithm"] = self.algorithm
        return event


class RoomKey(ToDeviceEvent):
    class Algorithm(Enum):
        megolm_v1_aes_sha2 = "m.megolm.v1.aes-sha2"

    type = "m.room_key"
    make = Sources(
        algorithm   = ("content", "algorithm"),
        room_id     = ("content", "room_id"),
        session_id  = ("content", "session_id"),
        session_key = ("content", "session_key"),
    )

    algorithm:   Algorithm
    room_id:     RoomId
    session_id:  str
    session_key: str
