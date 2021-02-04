from __future__ import annotations

import json
import logging as log
from datetime import datetime, timedelta
from math import floor
from typing import Any, Dict, Optional, Sequence, Type, TypeVar, Union

from pydantic import ValidationError

from ..typing import EventId, RoomId, UserId
from ..utils import Model, deep_find_subclasses

EvT        = TypeVar("EvT", bound="Event")
EventT     = Union["Event", EvT]
MatrixPath = Union[str, Sequence[str]]
_Missing   = object()


class Event(Model):
    class Matrix:
        pass

    type: Optional[str] = None

    source:           Dict[str, Any]            = {}
    validation_error: Optional[ValidationError] = None

    encrypted_source:              Optional[Dict[str, Any]] = None
    decrypted_payload:             Optional[Dict[str, Any]] = None
    decryption_verification_error: Optional[Exception]      = None

    __repr_exclude__ = [lambda self: None if type(self) is Event else "source"]


    class Config:
        arbitrary_types_allowed = True  # needed for exception fields

        json_encoders = {
            datetime: lambda v: floor(v.timestamp() * 1000),
            timedelta: lambda v: floor(v.total_seconds() * 1000),
        }


    @classmethod
    def fields_from_matrix(cls, event: Dict[str, Any]) -> Dict[str, Any]:
        fields = {}

        for parent_class in cls.__bases__:
            if issubclass(parent_class, Event):
                fields.update(parent_class.fields_from_matrix(event))

        def get(path: MatrixPath) -> Any:
            data = event
            path = (path,) if isinstance(path, str) else path

            for part in path:
                data = data.get(part, _Missing)
                if data is _Missing:
                    break

            return data

        fields.update({
            k: get(v) for k, v in cls.Matrix.__dict__.items()
            if not k.startswith("_")
        })
        fields = {k: v for k, v in fields.items() if v is not _Missing}

        fields["source"] = event
        return fields


    @classmethod
    def from_matrix(cls: Type[EvT], event: Dict[str, Any]) -> EventT:
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
        cls_type = cls.__fields__["type"].default
        return bool(cls_type) and cls_type == event.get("type")


    @classmethod
    def subtype_from_matrix(cls: Type[EvT], event: Dict[str, Any]) -> EventT:
        for subclass in deep_find_subclasses(cls):
            if subclass.matches_event(event):
                return subclass.from_matrix(event)

        return cls.from_matrix(event)


    @classmethod
    def subtype_from_fields(cls: Type[EvT], fields: Dict[str, Any]) -> EventT:
        for subclass in deep_find_subclasses(cls):
            if subclass.matches_event(fields["source"]):
                return subclass(**fields)

        return cls(**fields)


    @property
    def matrix(self) -> Dict[str, Any]:
        event: Dict[str, Any] = self.source.copy()

        for field, value in json.loads(self.json(exclude_unset=True)).items():
            for cls in (type(self), *type(self).__bases__):
                if issubclass(cls, Event) and hasattr(cls.Matrix, field):
                    mx_path = getattr(cls.Matrix, field)
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
    class Matrix:
        sender = "sender"

    sender: Optional[UserId] = None


class RoomEvent(Event):
    class Matrix:
        event_id = "event_id"
        sender   = "sender"
        date     = "origin_server_ts"
        room_id  = "room_id"

    sender:   Optional[UserId]   = None
    event_id: Optional[EventId]  = None
    date:     Optional[datetime] = None
    room_id:  Optional[RoomId]   = None

    def __lt__(self, other: "RoomEvent") -> bool:
        if self.date is None or other.date is None:
            raise TypeError(f"Can't compare None date: {self}, {other}")

        return self.date < other.date


class StateEvent(RoomEvent):
    class Matrix:
        state_key = "state_key"

    state_key: str
