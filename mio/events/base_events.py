from __future__ import annotations

import json
import logging as log
from datetime import datetime, timedelta
from math import floor
from typing import (
    Any, ClassVar, Dict, List, Optional, Tuple, Type, TypeVar, Union,
)

from pydantic import BaseModel, ValidationError
from pydantic.main import ModelMetaclass

from ..typing import EventId, RoomId, UserId
from ..utils import deep_find_subclasses
from .utils import Sources

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
    validation_error: Optional[ValidationError] = None

    encrypted_source:              Optional[Dict[str, Any]] = None
    decrypted_payload:             Optional[Dict[str, Any]] = None
    decryption_verification_error: Optional[Exception]      = None

    class Config:
        arbitrary_types_allowed = True  # needed for exception fields

        json_encoders = {
            datetime: lambda v: floor(v.timestamp() * 1000),
            timedelta: lambda v: floor(v.total_seconds() * 1000),
        }

    def __repr_args__(self) -> List[Tuple[Optional[str], Any]]:
        return [
            (name, value) for name, value in super().__repr_args__()
            if name != "source" or not self.type
        ]

    @classmethod
    def fields_from_matrix(cls, event: Dict[str, Any]) -> Dict[str, Any]:
        fields = {}

        for parent_class in cls.__bases__:
            if issubclass(parent_class, Event):
                fields.update(parent_class.fields_from_matrix(event))

        fields.update(cls.make.fields_from_matrix(event))
        return fields

    @classmethod
    def from_source(cls: Type[EvT], event: Dict[str, Any]) -> EventT:
        try:
            return cls(**cls.fields_from_matrix(event))
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

    @property
    def matrix(self) -> Dict[str, Any]:
        event: Dict[str, Any] = {"type": self.type, **self.source}

        for field, value in json.loads(self.json(exclude_unset=True)).items():
            for cls in (type(self), *type(self).__bases__):
                if issubclass(cls, Event) and field in cls.make.fields:
                    mx_path = cls.make.fields[field]
                    break
            else:
                continue

            mx_path = (mx_path,) if isinstance(mx_path, str) else mx_path
            dct     = event

            for part in mx_path[:-1]:
                dct = dct.setdefault(part, {})

            dct[mx_path[-1]] = value

        return event


class ToDeviceEvent(Event):
    make = Sources(sender="sender")

    sender: Optional[UserId] = None


class RoomEvent(Event):
    make = Sources(
        event_id = "event_id",
        sender   = "sender",
        date     = "origin_server_ts",
        room_id  = "room_id",
    )

    sender:   Optional[UserId]   = None
    event_id: Optional[EventId]  = None
    date:     Optional[datetime] = None
    room_id:  Optional[RoomId]   = None


class StateEvent(RoomEvent):
    make = Sources(state_key="state_key")

    state_key: str
