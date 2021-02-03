from typing import Optional

from ..typing import EventId
from .base_events import RoomEvent
from .utils import Sources


class Redaction(RoomEvent):
    type = "m.room.redaction"
    make = Sources(redacts="redacts", reason=("content", "reason"))

    redacts: EventId
    reason:  Optional[str] = None
