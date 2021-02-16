from datetime import timedelta
from enum import Enum
from typing import Any, Dict

from ...events.base_events import Event, RoomEvent, StateEvent, ToDeviceEvent
from ...typing import EmptyString, RoomId, UserId
from ...utils import Const, Model


class Algorithm(Enum):
    olm_v1    = "m.olm.v1.curve25519-aes-sha2"
    megolm_v1 = "m.megolm.v1.aes-sha2"


class EncryptionSettings(StateEvent):
    class Matrix:
        sessions_max_age      = ("content", "rotation_period_ms")
        sessions_max_messages = ("content", "rotation_period_msgs")
        algorithm             = ("content", "algorithm")

    type = Const("m.room.encryption")

    state_key:             EmptyString
    sessions_max_age:      timedelta = timedelta(weeks=1)
    sessions_max_messages: int       = 100
    algorithm:             str       = Algorithm.megolm_v1.value


class Olm(Event):
    class Cipher(Model):
        class Type(Enum):
            prekey = 0
            normal = 1

        type: Type
        body: str

    class Matrix:
        algorithm         = ("content", "algorithm")
        sender            = "sender"
        sender_curve25519 = ("content", "sender_key")
        ciphertext        = ("content", "ciphertext")

    type:      str = Const("m.room.encrypted")
    algorithm: str = Const(Algorithm.olm_v1.value)

    sender:            UserId
    sender_curve25519: str
    ciphertext:        Dict[str, Cipher]  # {recipient_curve_25519: Cipher}

    @classmethod
    def matches_event(cls, event: Dict[str, Any]) -> bool:
        cls_algo = cls.__fields__["algorithm"].default
        has_algo = bool(cls_algo)
        algo     = event.get("content", {}).get("algorithm")
        return super().matches_event(event) and has_algo and cls_algo == algo


class Megolm(RoomEvent):
    class Matrix:
        algorithm         = ("content", "algorithm")
        sender_curve25519 = ("content", "sender_key")
        ciphertext        = ("content", "ciphertext")
        device_id         = ("content", "device_id")
        session_id        = ("content", "session_id")

    type:      str = Const("m.room.encrypted")
    algorithm: str = Const(Algorithm.megolm_v1.value)

    sender_curve25519: str
    ciphertext:        str
    device_id:         str
    session_id:        str

    @classmethod
    def matches_event(cls, event: Dict[str, Any]) -> bool:
        cls_algo = cls.__fields__["algorithm"].default
        has_algo = bool(cls_algo)
        algo     = event.get("content", {}).get("algorithm")
        return super().matches_event(event) and has_algo and cls_algo == algo


class RoomKey(ToDeviceEvent):
    class Matrix:
        algorithm   = ("content", "algorithm")
        room_id     = ("content", "room_id")
        session_id  = ("content", "session_id")
        session_key = ("content", "session_key")

    type = Const("m.room_key")

    algorithm:   Algorithm
    room_id:     RoomId
    session_id:  str
    session_key: str
