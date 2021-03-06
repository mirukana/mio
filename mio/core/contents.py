# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from dataclasses import dataclass
from typing import ClassVar, Optional, Type, TypeVar, Union

from .data import JSON, JSONLoadError, Runtime
from .errors import MioError
from .utils import DictS

EventContentType = Union[Type["EventContent"], "EventContent", str]
ContentT         = TypeVar("ContentT", bound="EventContent")


@dataclass
class EventContent(JSON):
    type: ClassVar[Runtime[Optional[str]]] = None

    @classmethod
    def from_dict(
        cls: Type[ContentT], data: DictS, parent: Optional[JSON] = None,
    ) -> ContentT:
        try:
            return super().from_dict(data, parent)
        except JSONLoadError as e:
            raise InvalidContent(data, e)

    @classmethod
    def matches(cls, event: DictS) -> bool:
        return bool(cls.type) and cls.type == event.get("type")

    @property
    def _redacted(self) -> "EventContent":
        from ..rooms.contents.changes import Redacted
        return Redacted()


class UnknownType(MioError):
    type: Optional[str]


@dataclass
class InvalidContent(Exception, EventContent):
    source: Runtime[DictS]
    error:  Runtime[Union[JSONLoadError, UnknownType]]

    @property
    def dict(self) -> DictS:
        return self.source


def str_type(content_type: EventContentType) -> str:
    if isinstance(content_type, (EventContent, type)):
        assert content_type.type
        return content_type.type
    return content_type
