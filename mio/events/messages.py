from typing import Any, Dict, Optional

from ..utils import Const
from .base_events import RoomEvent


class Message(RoomEvent):
    class Matrix:
        msgtype = ("content", "msgtype")
        body    = ("content", "body")

    type:    str           = Const("m.room.message")
    msgtype: Optional[str] = None

    body: str

    @classmethod
    def matches_event(cls, event: Dict[str, Any]) -> bool:
        cls_msgtype = cls.__fields__["msgtype"].default
        if not cls_msgtype:
            return False

        msgtype = event.get("content", {}).get("msgtype")
        return super().matches_event(event) and cls_msgtype == msgtype


class TextKind(Message):
    class Matrix:
        format         = ("content", "format")
        formatted_body = ("content", "formatted_body")

    format:         Optional[str] = None
    formatted_body: Optional[str] = None


class Text(TextKind):
    msgtype = Const("m.text")


class Emote(TextKind):
    msgtype = Const("m.emote")


class Notice(TextKind):
    msgtype = Const("m.notice")
