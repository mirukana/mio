from typing import Any, ClassVar, Dict, Optional

from . import Event, RoomEvent, Sources, EventMeta

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
    def subtype_from_source(cls, event: Dict[str, Any]) -> "Event":
        msgtype = event.get("content", {}).get("msgtype", "")

        if msgtype:
            for subclass in cls.__subclasses__():
                if subclass.msgtype == msgtype:
                    return subclass.subtype_from_source(event)

        return cls.from_source(event)


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
