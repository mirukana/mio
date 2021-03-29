from dataclasses import dataclass
from typing import Optional, Set

from ...core.contents import EventContent
from ...core.types import UserId


@dataclass
class Redaction(EventContent):
    type = "m.room.redaction"

    reason: Optional[str] = None


@dataclass
class Typing(EventContent):
    type    = "m.typing"
    aliases = {"users": "user_ids"}

    users: Set[UserId]
