import logging as log
from dataclasses import dataclass, field
from typing import Generic, Optional, Type, TypeVar

from .contents import Content, ContentT, InvalidContent
from .data import JSON, JSONLoadError, Runtime
from .types import DictS
from .utils import deep_find_subclasses, deep_merge_dict

EventT = TypeVar("EventT", bound="Event")


@dataclass
class Event(JSON, Generic[ContentT]):
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
    def from_dict(cls: Type[EventT], data: DictS, parent) -> EventT:
        content = cls._get_content(data, data.get("content", {}))

        try:
            data = {**data, "source": data, "content": content}
            return super().from_dict(data, parent)
        except JSONLoadError as e:
            log.error("Failed parsing %s from %r: %r", cls.__name__, data, e)
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
class InvalidEvent(Exception, Event[ContentT]):
    source:     Runtime[DictS]  # repr=True, unlike Event
    content:    Runtime[ContentT]
    error:      Runtime[JSONLoadError]
