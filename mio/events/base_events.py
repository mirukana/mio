import logging as log
from datetime import datetime
from typing import (
    Any, ClassVar, Dict, List, Optional, Tuple, Type, TypeVar, Union,
)

from pydantic import BaseModel, ValidationError
from pydantic.main import ModelMetaclass

from ..client_modules.encryption.decryption_meta import DecryptionMetadata
from ..utils import deep_find_subclasses
from . import EventId, Sources, UserId

EvT    = TypeVar("EvT", bound="Event")
EventT = Union["Event", EvT]


class EventMeta(ModelMetaclass):
    def __new__(mcs, name, bases, namespace, **kwargs):
        # Workaround for https://github.com/samuelcolvin/pydantic/issues/2061
        annotations         = namespace.setdefault("__annotations__", {})
        annotations["type"] = ClassVar[Optional[str]]
        annotations["make"] = ClassVar[Sources]
        return super().__new__(mcs, name, bases, namespace, **kwargs)


class Event(BaseModel, metaclass=EventMeta):
    type: ClassVar[Optional[str]] = None
    make: ClassVar[Sources]       = Sources()

    source:           Dict[str, Any]            = {}
    decryption:       DecryptionMetadata        = DecryptionMetadata()
    validation_error: Optional[ValidationError] = None

    class Config:
        arbitrary_types_allowed = True  # needed for `validation_error` field

    def __repr_args__(self) -> List[Tuple[Optional[str], Any]]:
        return [
            (name, value) for name, value in super().__repr_args__()
            if name != "source" or not self.type
        ]

    @classmethod
    def find_fields(cls, event: Dict[str, Any]) -> Dict[str, Any]:
        fields = {}

        for parent_class in cls.__bases__:
            if issubclass(parent_class, Event):
                fields.update(parent_class.find_fields(event))

        fields.update(cls.make.find_fields(event))
        return fields

    @classmethod
    def from_source(cls: Type[EvT], event: Dict[str, Any]) -> EventT:
        try:
            return cls(**cls.find_fields(event))
        except ValidationError as e:
            log.warning(
                "Failed validating event %r for type %s: %s\n",
                event, cls.__name__, e,
            )
            return Event(source=event, validation_error=e)

    @classmethod
    def matches_event(cls, event: Dict[str, Any]) -> bool:
        return cls.type == event.get("type")

    @classmethod
    def subtype_from_source(cls: Type[EvT], event: Dict[str, Any]) -> EventT:
        for subclass in deep_find_subclasses(cls):
            if subclass.matches_event(event):
                return subclass.from_source(event)

        return cls.from_source(event)


class ToDeviceEvent(Event):
    make = Sources(sender="sender")

    sender: UserId


class RoomEvent(Event):
    make = Sources(
        event_id = "event_id",
        sender   = "sender",
        date     = "origin_server_ts",
    )

    sender:    UserId
    event_id:  Optional[EventId]  = None
    date:      Optional[datetime] = None


class StateEvent(RoomEvent):
    make = Sources(state_key="state_key")

    state_key: str
