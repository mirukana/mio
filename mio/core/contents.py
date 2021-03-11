import logging as log
from dataclasses import dataclass
from typing import ClassVar, Optional, Type, TypeVar

from .data import JSON, JSONLoadError, Runtime
from .types import DictS

ContentT = TypeVar("ContentT", bound="Content")


@dataclass
class Content(JSON):
    type: ClassVar[Optional[str]] = None

    @classmethod
    def from_dict(
        cls: Type[ContentT], data: DictS, parent: Optional["JSON"] = None,
    ) -> ContentT:
        try:
            return super().from_dict(data, parent)
        except JSONLoadError as e:
            log.error("Failed parsing %s from %r: %r", cls.__name__, data, e)
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
