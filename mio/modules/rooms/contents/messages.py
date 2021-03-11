from dataclasses import dataclass
from typing import Any, ClassVar, Dict, Optional

from ....core.contents import EventContent


@dataclass
class Message(EventContent):
    type:    ClassVar[Optional[str]] = "m.room.message"
    msgtype: ClassVar[Optional[str]] = None

    body: str

    @classmethod
    def matches(cls, event: Dict[str, Any]) -> bool:
        if not cls.msgtype:
            return False

        msgtype = event.get("content", {}).get("msgtype")
        return super().matches(event) and cls.msgtype == msgtype


@dataclass
class TextKind(Message):
    format:         Optional[str] = None
    formatted_body: Optional[str] = None


@dataclass
class Text(TextKind):
    msgtype = "m.text"


@dataclass
class Emote(TextKind):
    msgtype = "m.emote"


@dataclass
class Notice(TextKind):
    msgtype = "m.notice"
