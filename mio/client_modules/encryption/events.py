from datetime import timedelta
from enum import Enum
from typing import Any, ClassVar, Dict

from ...events.base_events import Content, dataclass
from ...typing import RoomId, UserId


@dataclass
class Algorithm(Enum):
    olm_v1    = "m.olm.v1.curve25519-aes-sha2"
    megolm_v1 = "m.megolm.v1.aes-sha2"


@dataclass
class EncryptionSettings(Content):
    type    = "m.room.encryption"
    aliases = {
        "sessions_max_age": "rotation_period_ms",
        "sessions_max_messages": "rotation_period_msgs",
    }

    sessions_max_age:      timedelta = timedelta(weeks=1)
    sessions_max_messages: int       = 100
    algorithm:             str       = Algorithm.megolm_v1.value


@dataclass
class Olm(Content):
    @dataclass
    class Cipher:
        class Type(Enum):
            prekey = 0
            normal = 1

        type: Type
        body: str

    type    = "m.room.encrypted"
    aliases = {"sender_curve25519": "sender_key"}

    algorithm: ClassVar[str] = Algorithm.olm_v1.value

    sender:            UserId
    sender_curve25519: str
    ciphertext:        Dict[str, Cipher]  # {recipient_curve_25519: Cipher}

    @classmethod
    def matches(cls, event: Dict[str, Any]) -> bool:
        algo = event.get("content", {}).get("algorithm")
        return super().matches(event) and cls.algorithm == algo


@dataclass
class Megolm(Content):
    type    = "m.room.encrypted"
    aliases = {"sender_curve25519": "sender_key"}

    algorithm: ClassVar[str] = Algorithm.megolm_v1.value

    sender_curve25519: str
    ciphertext:        str
    device_id:         str
    session_id:        str

    @classmethod
    def matches(cls, event: Dict[str, Any]) -> bool:
        algo = event.get("content", {}).get("algorithm")
        return super().matches(event) and cls.algorithm == algo


@dataclass
class RoomKey(Content):
    type = "m.room_key"

    algorithm:   Algorithm
    room_id:     RoomId
    session_id:  str
    session_key: str
