from typing import Optional

from . import EventId, RoomEvent, Sources


class Redaction(RoomEvent):
    type = "m.room.redaction"
    make = Sources(redacts="redacts", reason=("content", "reason"))

    redacts: EventId
    reason:  Optional[str] = None
