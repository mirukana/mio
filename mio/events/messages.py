from typing import Any, ClassVar, Dict, Optional

from . import EventMeta, RoomEvent, Sources

_TEXT_SOURCE = Sources(
    format         = ("content", "format"),
    formatted_body = ("content", "formatted_body"),
)


class MessageMeta(EventMeta):
    def __new__(mcs, name, bases, namespace, **kwargs):
        ann            = namespace.setdefault("__annotations__", {})
        ann["msgtype"] = ClassVar[Optional[str]]
        return super().__new__(mcs, name, bases, namespace, **kwargs)


class Message(RoomEvent, metaclass=MessageMeta):
    type = "m.room.message"
    make = Sources(
        msgtype = ("content", "msgtype"),
        body    = ("content", "body"),
    )

    msgtype: ClassVar[Optional[str]] = None

    body: str

    @classmethod
    def matches_event(cls, event: Dict[str, Any]) -> bool:
        msgtype = event.get("content", {}).get("msgtype")
        return cls.type == event.get("type") and cls.msgtype == msgtype

    @property
    def matrix(self) -> Dict[str, Any]:
        event = super().matrix
        # make sure this is always included
        event["content"]["msgtype"] = self.msgtype
        return event


class Text(Message):
    msgtype = "m.text"
    make    = _TEXT_SOURCE

    format:         Optional[str] = None
    formatted_body: Optional[str] = None


class Emote(Message):
    msgtype = "m.emote"
    make    = _TEXT_SOURCE

    format:         Optional[str] = None
    formatted_body: Optional[str] = None


class Notice(Message):
    msgtype = "m.notice"
    make    = _TEXT_SOURCE

    format:         Optional[str] = None
    formatted_body: Optional[str] = None
