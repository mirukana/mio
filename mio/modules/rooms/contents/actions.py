from dataclasses import dataclass
from typing import Optional

from ....core.contents import EventContent


@dataclass
class Redaction(EventContent):
    type = "m.room.redaction"

    reason: Optional[str] = None
