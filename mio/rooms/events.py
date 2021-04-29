# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional, Type, TypeVar, Union

from ..core.contents import ContentT
from ..core.data import Parent, Runtime
from ..core.events import Event
from ..core.ids import EventId, RoomId, UserId
from ..core.utils import DictS, get_logger
from ..devices.device import Device
from ..e2e.contents import Megolm
from ..e2e.errors import MegolmDecryptionError, MegolmVerificationError

if TYPE_CHECKING:
    from .room import Room

LOG = get_logger()

StateEvT    = TypeVar("StateEvT", bound="StateEvent")
DecryptInfo = Optional["TimelineDecryptInfo"]


@dataclass
class TimelineEvent(Event[ContentT]):
    aliases = {"id": "event_id", "date": "origin_server_ts"}

    room:       Parent["Room"] = field(repr=False)
    content:    ContentT
    id:         EventId
    sender:     UserId
    date:       datetime
    redacts:    Optional[EventId]    = None
    room_id:    Optional[RoomId]     = None
    decryption: Runtime[DecryptInfo] = None
    historic:   Runtime[bool]        = False
    # TODO: unsigned

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
                LOG.exception("Failed decrypting %r", self)

            self.decryption = TimelineDecryptInfo(self, error=e)
            return self

        clear = type(self).from_dict({**self.source, **payload}, self.room)

        clear.decryption = TimelineDecryptInfo(
            self, payload, chain, verification_errors=errors,
        )

        if errors and log:
            LOG.warning("Error verifying decrypted event %r\n", clear)

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
class StateBase(Event[ContentT]):
    room:      Parent["Room"] = field(repr=False)
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
class EphemeralEvent(Event[ContentT]):
    room:      Parent["Room"] = field(repr=False)
    content:   ContentT
