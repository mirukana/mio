# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import TYPE_CHECKING, Dict, List, Optional, Type, TypeVar, Union
from uuid import uuid4

from mio.core.utils import remove_none

from ..core.contents import ContentT
from ..core.data import Parent, Runtime
from ..core.events import Event
from ..core.ids import EventId, UserId
from ..core.logging import MioLogger
from ..core.utils import DictS
from ..devices.device import Device
from ..e2e.contents import Megolm
from ..e2e.errors import MegolmDecryptionError, MegolmVerificationError
from ..net.errors import ServerError

if TYPE_CHECKING:
    from .contents.changes import Redaction
    from .room import Room

RoomEvT     = TypeVar("RoomEvT", bound="RoomEvent")
StateEvT    = TypeVar("StateEvT", bound="StateEvent")
DecryptInfo = Optional["TimelineDecryptInfo"]


class SendStep(Enum):
    failed  = auto()
    sending = auto()
    sent    = auto()
    synced  = auto()


@dataclass
class RoomEvent(Event[ContentT]):
    room: Parent["Room"] = field(repr=False)


    @property
    def logger(self) -> MioLogger:
        return self.room.client


    async def _redact(self, reason: Optional[str] = None) -> EventId:
        ev_id = getattr(self, "id", "")
        tx_id = str(uuid4())

        echo: TimelineEvent[Redaction] = TimelineEvent.from_dict({
            "type":             "m.room.redaction",
            "content":          {"reason": reason},
            "event_id":         f"$echo.{tx_id}",
            "sender":           self.room.client.user_id,
            "origin_server_ts": datetime.now().timestamp() * 1000,
            "unsigned":         {"transaction_id": tx_id},
            "redacts":          ev_id,
        }, parent=self.room)
        echo.sending = SendStep.sending
        await self.room.timeline._register_events(echo)

        net = self.room.net
        url = net.api / "rooms" / self.room.id / "redact" / ev_id / tx_id

        try:
            reply = await net.put(url, remove_none({"reason": reason}))
        except ServerError:
            timeline                  = self.room.timeline
            timeline[echo.id].sending = SendStep.failed
            await timeline._register_events(timeline[echo.id])
            raise

        timeline = self.room.timeline
        old      = timeline._data.pop(echo.id)
        sent     = SendStep.sent
        redac_id = EventId(reply.json["event_id"])
        await timeline._register_events(old.but(id=redac_id, sending=sent))
        return redac_id


    def _redacted(
        self: RoomEvT, redaction: "TimelineEvent[Redaction]",
    ) -> RoomEvT:
        return self.but(content=self.content._redacted, redacted_by=redaction)


@dataclass
class TimelineEvent(RoomEvent[ContentT]):
    aliases = {
        "id":             "event_id",
        "date":           "origin_server_ts",
        "transaction_id": ("unsigned", "transaction_id"),
        "redacted_by":    ("unsigned", "redacted_because"),
    }

    content:        ContentT
    id:             EventId
    sender:         UserId
    date:           datetime
    state_key:      Optional[str]                        = None
    redacts:        Optional[EventId]                    = None
    redacted_by:    Optional["TimelineEvent[Redaction]"] = None
    transaction_id: Optional[str]                        = None
    decryption:     Runtime[DecryptInfo]                 = None
    historic:       Runtime[bool]                        = False
    sending:        Runtime[SendStep]                    = SendStep.synced


    def __lt__(self, other: "TimelineEvent") -> bool:
        return self.date < other.date


    @property
    def receipts(self) -> Dict[str, Dict[UserId, Optional[datetime]]]:
        return self.room.receipts_by_event.get(self.id, {})


    async def redact(self, reason: Optional[str] = None) -> EventId:
        return await self._redact(reason)


    async def _decrypted(self, log: bool = True) -> "TimelineEvent":
        if not isinstance(self.content, Megolm):
            return self

        decrypt = self.room.client.e2e._decrypt_megolm_payload

        try:
            payload, chain, errors = await decrypt(self)  # type: ignore
        except MegolmDecryptionError as e:
            if log:
                self.logger.exception("Failed decrypting {}", self)

            self.decryption = TimelineDecryptInfo(self, error=e)
            return self

        clear = type(self).from_dict({**self.source, **payload}, self.room)

        clear.decryption = TimelineDecryptInfo(
            self, payload, chain, verification_errors=errors,
        )

        if errors and log:
            self.logger.warn("Error verifying decrypted event {}", clear)

        return clear


@dataclass
class TimelineDecryptInfo:
    original:      "TimelineEvent"          = field(repr=False)
    payload:       Optional[DictS]          = field(default=None, repr=False)
    forward_chain: List[Union[Device, str]] = field(default_factory=list)

    error:               Optional[MegolmDecryptionError] = None
    verification_errors: List[MegolmVerificationError]   = field(
        default_factory=list,
    )


@dataclass
class StateBase(RoomEvent[ContentT]):
    content:   ContentT
    state_key: str
    sender:    UserId

    def __post_init__(self) -> None:
        if type(self) is StateBase:  # pragma: no cover
            self.from_disk: bool = False  # mypy hack


@dataclass
class InvitedRoomStateEvent(StateBase[ContentT]):
    content:   ContentT
    from_disk: Runtime[bool] = False


@dataclass
class StateEvent(StateBase[ContentT]):
    aliases = {
        "id":          "event_id",
        "date":        "origin_server_ts",
        "previous":    ("unsigned", "prev_content"),
        "redacted_by": ("unsigned", "redacted_because"),
    }

    content:     ContentT
    id:          EventId
    date:        datetime
    previous:    Optional[ContentT]                   = None
    redacted_by: Optional[TimelineEvent["Redaction"]] = None
    from_disk:   Runtime[bool]                        = False

    @classmethod
    def from_dict(
        cls: Type[StateEvT], data: DictS, parent: "Room",
    ) -> StateEvT:

        prev_dict = data.get("unsigned", {}).get("prev_content", {})

        if prev_dict:
            content = cls._get_content(data, prev_dict)
            data.setdefault("unsigned", {})["prev_content"] = content

        return super().from_dict(data, parent)


    async def redact(self, reason: Optional[str] = None) -> EventId:
        return await self._redact(reason)


@dataclass
class EphemeralEvent(RoomEvent[ContentT]):
    content: ContentT
