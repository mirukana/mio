from dataclasses import dataclass
from typing import ClassVar, Optional, Type, TypeVar, Union

from .data import JSON, JSONLoadError, Runtime
from .errors import MioError
from .types import DictS
from .utils import get_logger

LOG = get_logger()

ContentT = TypeVar("ContentT", bound="EventContent")


@dataclass
class EventContent(JSON):
    type: ClassVar[Runtime[Optional[str]]] = None

    @classmethod
    def from_dict(
        cls: Type[ContentT], data: DictS, parent: Optional["JSON"] = None,
    ) -> ContentT:
        try:
            return super().from_dict(data, parent)
        except JSONLoadError as e:
            LOG.error("Failed parsing %s from %r: %r", cls.__name__, data, e)
            raise InvalidContent(data, e)

    @classmethod
    def matches(cls, event: DictS) -> bool:
        return bool(cls.type) and cls.type == event.get("type")


class NoMatchingType(MioError):
    pass


@dataclass
class InvalidContent(Exception, EventContent):
    source: Runtime[DictS]
    error:  Runtime[Union[JSONLoadError, NoMatchingType]]

    @property
    def dict(self) -> DictS:
        return self.source
