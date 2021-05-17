# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from dataclasses import dataclass, field
from typing import Generic, Optional, Type, TypeVar

from ..core.logging import MioLogger
from .contents import ContentT, EventContent, InvalidContent, UnknownType
from .data import JSON, JSONLoadError, Runtime
from .utils import DictS, deep_find_subclasses, deep_merge_dict

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
        dct         = self.source
        dct["type"] = self.type
        deep_merge_dict(dct, super().dict)
        return dct

    @property
    def logger(self) -> MioLogger:
        raise NotImplementedError

    @classmethod
    def from_dict(cls: Type[EventT], data: DictS, parent) -> EventT:
        content = cls._get_content(data, data.get("content", {}))
        data    = {**data, "source": data, "content": content}

        try:
            obj = super().from_dict(data, parent)
        except JSONLoadError as e:
            raise InvalidEvent(data, content, e)

        if isinstance(obj.content, InvalidContent):
            error = obj.content.error
            obj.logger.warn("Couldn't parse content of {}: {}", obj, error)

        return obj

    @classmethod
    def _get_content(cls, event: DictS, content: DictS) -> EventContent:
        # Make sure python knows about all the existing EventContent subclasses
        from ..core import contents  # noqa
        from ..rooms.contents import actions, messages, settings, users  # noqa

        content_subs = deep_find_subclasses(EventContent)

        try:
            content_cls = next(c for c in content_subs if c.matches(event))
        except StopIteration:
            return InvalidContent(content, UnknownType(event.get("type")))

        try:
            return content_cls.from_dict(content)
        except InvalidContent as e:
            return e


@dataclass
class InvalidEvent(Exception, Event[ContentT]):
    source:     Runtime[DictS]  # repr=True, unlike Event
    content:    Runtime[ContentT]
    error:      Runtime[JSONLoadError]
