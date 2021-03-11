import logging as log
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, ClassVar, Generic, Optional, Type, TypeVar

from ..typing import EventId, RoomId, UserId
from ..utils import (
    JSON, DictS, JSONLoadError, Parent, Runtime, deep_find_subclasses,
    deep_merge_dict,
)

if TYPE_CHECKING:
    from ..base_client import Client
    from ..client_modules.rooms import Room

EventT   = TypeVar("EventT", bound="Event")
ContentT = TypeVar("ContentT", bound="Content")
StateEvT = TypeVar("StateEvT", bound="StateEvent")


@dataclass
class Decryption:
    original:           "Event"
    payload:            DictS
    verification_error: Optional[Exception] = None


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
class TimelineEvent(Event[ContentT]):
    aliases = {"id": "event_id", "date": "origin_server_ts"}

    room:       Parent["Room"] = field(repr=False)
    content:    ContentT
    id:         EventId
    sender:     UserId
    date:       datetime
    redacts:    Optional[EventId]             = None
    room_id:    Optional[RoomId]              = None
    decryption: Runtime[Optional[Decryption]] = field(default=None, repr=False)
    # TODO: unsigned

    def __lt__(self, other: "TimelineEvent") -> bool:
        return self.date < other.date

    async def decrypted(self) -> "TimelineEvent":
        from ..client_modules.encryption.events import Megolm
        if not isinstance(self.content, Megolm):
            return self

        decrypt            = self.room.client.e2e.decrypt_megolm_payload
        payload, verif_err = await decrypt(self.room.id, self)  # type: ignore

        clear = type(self).from_dict({**self.source, **payload}, self.room)
        clear.decryption = Decryption(self, payload, verif_err)

        if verif_err:
            log.warning("Error verifying decrypted event %r\n", clear)

        return clear


@dataclass
class StateKind(Event[ContentT]):
    room:      Parent["Room"] = field(repr=False)
    content:   ContentT
    state_key: str
    sender:    UserId


@dataclass
class InvitedRoomStateEvent(StateKind[ContentT]):
    content: ContentT


@dataclass
class StateEvent(StateKind[ContentT]):
    aliases = {
        "id": "event_id",
        "date": "origin_server_ts",
        "previous": ("unsigned", "prev_content"),
    }

    content:  ContentT
    id:       EventId
    date:     datetime
    previous: Optional[ContentT] = None
    room_id:  Optional[RoomId]   = None

    @classmethod
    def from_dict(
        cls: Type[StateEvT], data: DictS, parent: "Room",
    ) -> StateEvT:

        prev_dict = data.get("unsigned", {}).get("prev_content", {})

        if prev_dict:
            content = cls._get_content(data, prev_dict)
            data.setdefault("unsigned", {})["prev_content"] = content

        return super().from_dict(data, parent)


@dataclass
class ToDeviceEvent(Event[ContentT]):
    client:     Parent["Client"] = field(repr=False)
    content:    ContentT
    sender:     UserId
    decryption: Runtime[Optional[Decryption]] = field(default=None, repr=False)

    async def decrypted(self) -> "ToDeviceEvent":
        from ..client_modules.encryption.events import Olm
        if not isinstance(self.content, Olm):
            return self

        decrypt            = self.client.e2e.decrypt_olm_payload
        payload, verif_err = await decrypt(self)  # type: ignore

        clear = type(self).from_dict({**self.source, **payload}, self.client)
        clear.decryption = Decryption(self, payload, verif_err)

        if verif_err:
            log.warning("Error verifying decrypted event %r\n", clear)

        return clear


@dataclass
class InvalidEvent(Exception, Event[ContentT]):
    source:     Runtime[DictS]  # repr=True, unlike Event
    content:    Runtime[ContentT]
    error:      Runtime[JSONLoadError]
