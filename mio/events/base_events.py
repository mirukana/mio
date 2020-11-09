from datetime import datetime
from typing import Any, ClassVar, Dict, List, Optional, Tuple, Type

from pydantic import BaseModel
from pydantic.main import ModelMetaclass

from . import EventId, Sources, UserId


class EventMeta(ModelMetaclass):
    def __new__(mcs, name, bases, namespace, **kwargs):
        # Workaround for https://github.com/samuelcolvin/pydantic/issues/2061
        annotations         = namespace.setdefault("__annotations__", {})
        annotations["type"] = ClassVar[Optional[str]]
        annotations["make"] = ClassVar[Sources]
        return super().__new__(mcs, name, bases, namespace, **kwargs)


class Event(BaseModel, metaclass=EventMeta):
    type:              ClassVar[Optional[str]]            = None
    make:              ClassVar[Sources]                  = Sources()
    _types_subclasses: ClassVar[Dict[str, Type["Event"]]] = {}

    source: Dict[str, Any] = {}

    def __init_subclass__(cls, **kwargs) -> None:
        if cls.type:
            Event._types_subclasses[cls.type] = cls

    def __repr_args__(self) -> List[Tuple[Optional[str], Any]]:
        return [
            (name, value) for name, value in super().__repr_args__()
            if name != "source" or type(self) is Event
        ]

    @classmethod
    def find_fields(cls, event: Dict[str, Any]) -> Dict[str, Any]:
        fields = {}

        for parent_class in cls.__bases__:
            if issubclass(parent_class, Event):
                fields.update(parent_class.make.find_fields(event))

        fields.update(cls.make.find_fields(event))
        return fields

    @classmethod
    def from_source(cls, event: Dict[str, Any]) -> "Event":
        return cls(**cls.find_fields(event))

    @classmethod
    def subtype_from_source(cls, event: Dict[str, Any]) -> "Event":
        event_type = event.get("type", "")
        subclass   = cls._types_subclasses.get(event_type, Event)
        return subclass.from_source(event)


class StrippedState(Event):
    make = Sources(state_key="state_key", sender="sender")

    state_key: str
    sender:    UserId


class RoomEvent(Event):
    make = Sources(
        event_id  = "event_id",
        date      = "origin_server_ts",
        state_key = "state_key",
    )

    event_id:  EventId
    date:      datetime
    state_key: Optional[str] = None
