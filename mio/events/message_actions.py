from typing import Optional

from .base_events import Content, dataclass


@dataclass
class Redaction(Content):
    type = "m.room.redaction"

    reason: Optional[str] = None
