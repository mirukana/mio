from typing import Optional

from ..typing import EventId
from ..utils import Const
from .base_events import RoomEvent


class Redaction(RoomEvent):
    class Matrix:
        redacts = "redacts"
        reason  = ("content", "reason")

    type = Const("m.room.redaction")

    redacts: EventId
    reason:  Optional[str] = None
