import logging as log
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Optional, Type, TypeVar

from ..core.contents import ContentT
from ..core.data import Parent, Runtime
from ..core.events import Event
from ..core.types import DictS, EventId, RoomId, UserId
from ..e2e.contents import Megolm
from ..e2e.errors import MegolmVerificationError

if TYPE_CHECKING:
    from .room import Room

StateEvT    = TypeVar("StateEvT", bound="StateEvent")
DecryptInfo = Optional["TimelineDecryptInfo"]


@dataclass
class TimelineEvent(Event[ContentT]):
    aliases = {"id": "event_id", "date": "origin_server_ts"}

    room:       Parent["Room"]       = field(repr=False)
    content:    ContentT
    id:         EventId
    sender:     UserId
    date:       datetime
    redacts:    Optional[EventId]    = None
    room_id:    Optional[RoomId]     = None
    decryption: Runtime[DecryptInfo] = field(default=None, repr=False)
    # TODO: unsigned

    def __lt__(self, other: "TimelineEvent") -> bool:
        return self.date < other.date

    async def decrypted(self) -> "TimelineEvent":
        if not isinstance(self.content, Megolm):
            return self

        decrypt            = self.room.client.e2e.decrypt_megolm_payload
        payload, verif_err = await decrypt(self.room.id, self)  # type: ignore

        clear = type(self).from_dict({**self.source, **payload}, self.room)
        clear.decryption = TimelineDecryptInfo(self, payload, verif_err)

        if verif_err:
            log.warning("Error verifying decrypted event %r\n", clear)

        return clear


@dataclass
class TimelineDecryptInfo:
    original:           "TimelineEvent"
    payload:            DictS
    verification_error: Optional[MegolmVerificationError] = None


@dataclass
class StateBase(Event[ContentT]):
    room:      Parent["Room"] = field(repr=False)
    content:   ContentT
    state_key: str
    sender:    UserId


@dataclass
class InvitedRoomStateEvent(StateBase[ContentT]):
    content: ContentT


@dataclass
class StateEvent(StateBase[ContentT]):
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
