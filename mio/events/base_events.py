from datetime import datetime
from typing import Any, ClassVar, Dict, List, Optional, Tuple

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
    type: ClassVar[Optional[str]] = None
    make: ClassVar[Sources]       = Sources()

    source: Dict[str, Any] = {}

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
    def from_source(cls, event: Dict[str, Any]) -> "Event":
        return cls(**cls.find_fields(event))

    @classmethod
    def subtype_from_source(cls, event: Dict[str, Any]) -> "Event":
        event_type = event.get("type", "")

        if event_type:
            for subclass in cls.__subclasses__():
                if subclass.type == event_type:
                    return subclass.subtype_from_source(event)

        return cls.from_source(event)


class RoomEvent(Event):
    make = Sources(
        event_id  = "event_id",
        sender    = "sender",
        date      = "origin_server_ts",
        state_key = "state_key",
    )

    event_id:  EventId
    sender:    UserId
    date:      Optional[datetime] = None
    state_key: Optional[str]      = None
