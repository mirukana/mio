# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional, Type, TypeVar, Union

from ..core.contents import ContentT
from ..core.data import Parent, Runtime
from ..core.events import Event
from ..core.ids import EventId, RoomId, UserId
from ..core.logging import MioLogger
from ..core.utils import DictS
from ..devices.device import Device
from ..e2e.contents import Megolm
from ..e2e.errors import MegolmDecryptionError, MegolmVerificationError

if TYPE_CHECKING:
    from .room import Room

StateEvT    = TypeVar("StateEvT", bound="StateEvent")
DecryptInfo = Optional["TimelineDecryptInfo"]


@dataclass
class RoomEvent(Event[ContentT]):
    room: Parent["Room"] = field(repr=False)

    @property
    def logger(self) -> MioLogger:
        return self.room.client


@dataclass
class TimelineEvent(RoomEvent[ContentT]):
    aliases = {
        "id": "event_id",
        "date": "origin_server_ts",
        "transaction_id": ("unsigned", "transaction_id"),
    }

    content:        ContentT
    id:             EventId
    sender:         UserId
    date:           datetime
    redacts:        Optional[EventId]    = None
    room_id:        Optional[RoomId]     = None
    transaction_id: Optional[str]        = None
    decryption:     Runtime[DecryptInfo] = None
    historic:       Runtime[bool]        = False
    local_echo:     Runtime[bool]        = False
    # TODO: unsigned.{age,redacted_because}

    def __lt__(self, other: "TimelineEvent") -> bool:
        return self.date < other.date

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
        "id": "event_id",
        "date": "origin_server_ts",
        "previous": ("unsigned", "prev_content"),
    }

    content:   ContentT
    id:        EventId
    date:      datetime
    previous:  Optional[ContentT] = None
    room_id:   Optional[RoomId]   = None
    from_disk: Runtime[bool]      = False

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
class EphemeralEvent(RoomEvent[ContentT]):
    content: ContentT
