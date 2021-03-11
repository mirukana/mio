from dataclasses import dataclass
from typing import Optional

from ....core.contents import Content


@dataclass
class Redaction(Content):
    type = "m.room.redaction"

    reason: Optional[str] = None
