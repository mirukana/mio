from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar, Generic, Optional, Type, TypeVar

from ..typing import EventId, RoomId, UserId
from ..utils import (
    JSON, DictS, Frozen, JSONLoadError, Runtime, deep_find_subclasses,
    deep_merge_dict,
)

EventT   = TypeVar("EventT", bound="Event")
ContentT = TypeVar("ContentT", bound="Content")
StateEvT = TypeVar("StateEvT", bound="StateEvent")


@dataclass
class Decryption(Frozen):
    source:             DictS
    payload:            DictS
    verification_error: Optional[Exception] = None


@dataclass
class Content(JSON, Frozen):
    type: ClassVar[Optional[str]] = None

    @classmethod
    def from_dict(cls: Type[ContentT], data: DictS, **defaults) -> ContentT:
        try:
            return super().from_dict(data, **defaults)
        except JSONLoadError as e:
            raise InvalidContent(data, e)

    @classmethod
    def matches(cls, event: DictS) -> bool:
        return bool(cls.type) and cls.type == event.get("type")


@dataclass
class InvalidContent(Exception, Content):
    source: Runtime[DictS]
    error:  Runtime[JSONLoadError]

    @property
    def dict(self) -> DictS:
        return self.source


@dataclass
class Event(JSON, Frozen, Generic[ContentT]):
    source:  Runtime[DictS] = field(repr=False)
    content: ContentT

    @property
    def type(self) -> Optional[str]:
        return self.content.type or self.source.get("type")

    @property
    def dict(self) -> DictS:
        dct = self.source
        deep_merge_dict(dct, super().dict)
        return dct

    @classmethod
    def from_dict(cls: Type[EventT], data: DictS, **defaults) -> EventT:
        content = cls._get_content(data, data.get("content", {}))
        try:
            data = {**data, "source": data, "content": content}
            return super().from_dict(data, **defaults)
        except JSONLoadError as e:
            raise InvalidEvent(data, content, e)

    @classmethod
    def _get_content(cls, event: DictS, content: DictS) -> Content:
        content_subs = deep_find_subclasses(Content)
        content_cls  = next(
            (c for c in content_subs if c.matches(event)),
            InvalidContent,
        )
        try:
            return content_cls.from_dict(content)
        except InvalidContent as e:
            return e


@dataclass
class TimelineEvent(Event[ContentT]):
    aliases = {"id": "event_id", "date": "origin_server_ts"}

    content:    ContentT
    id:         EventId
    sender:     UserId
    date:       datetime
    redacts:    Optional[EventId]             = None
    room_id:    Optional[RoomId]              = None
    decryption: Runtime[Optional[Decryption]] = None
    # TODO: unsigned

    def __lt__(self, other: "TimelineEvent") -> bool:
        return self.date < other.date


@dataclass
class StateKind(Event[ContentT]):
    content:   ContentT
    state_key: str
    sender:    UserId


@dataclass
class InvitedRoomStateEvent(StateKind[ContentT]):
    content: ContentT


@dataclass
class StateEvent(StateKind[ContentT]):
    aliases = {
        "id": "event_id",
        "date": "origin_server_ts",
        "previous": ("unsigned", "prev_content"),
    }

    content:  ContentT
    id:       EventId
    date:     datetime
    previous: Optional[ContentT] = None
    room_id:  Optional[RoomId]   = None

    @classmethod
    def from_dict(cls: Type[StateEvT], data: DictS, **defaults) -> StateEvT:
        prev_dict = data.get("unsigned", {}).get("prev_content", {})

        if prev_dict:
            content = cls._get_content(data, prev_dict)
            data.setdefault("unsigned", {})["prev_content"] = content

        return super().from_dict(data, **defaults)


@dataclass
class ToDeviceEvent(Event[ContentT]):
    content:    ContentT
    sender:     UserId
    decryption: Runtime[Optional[Decryption]] = None


@dataclass
class InvalidEvent(Exception, Event[ContentT]):
    source:     Runtime[DictS]  # repr=True, unlike Event
    content:    Runtime[ContentT]
    error:      Runtime[JSONLoadError]
