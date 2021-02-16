from __future__ import annotations

from pathlib import Path
from typing import Optional, Set, Tuple
from uuid import uuid4

from pydantic import Field

from ...events.base_events import Event, RoomEvent, StateEvent
from ...events.room_state import Member
from ...typing import RoomId, UserId
from ...utils import AsyncInit, FileModel
from ..encryption.events import EncryptionSettings, Megolm


class Room(FileModel, AsyncInit):
    client:  Client
    id:      RoomId

    # Set by Room.handle_event
    inviter:    Optional[UserId]             = None  # TODO
    encryption: Optional[EncryptionSettings] = None
    members:    Set[UserId]                  = set()

    # Set by Synchronizer.handle_sync
    invited:              bool               = False
    left:                 bool               = False
    summary_heroes:       Tuple[UserId, ...] = ()
    summary_joined:       int                = 0
    summary_invited:      int                = 0
    unread_notifications: int                = 0
    unread_highlights:    int                = 0

    timeline: Timeline = Field(None)

    __json__         = {"exclude": {"client", "id", "timeline"}}
    __repr_exclude__ = ("client", "members", "timeline")


    async def __ainit__(self) -> None:
        self.timeline = await Timeline.load(self)


    @property
    def save_file(self) -> Path:
        return self.client.save_dir / "rooms" / self.id / "room.json"


    @classmethod
    async def load(cls, client: "Client", id: RoomId) -> "Room":
        file = client.save_dir / "rooms" / id / "room.json"
        data = await cls._read_json(file)
        return await cls(client=client, id=id, **data)


    async def handle_event(self, event: Event, state: bool = False) -> None:
        # TODO: handle_event**s** function that only saves at the end

        if not state:
            if isinstance(event, RoomEvent):
                await self.timeline.add_events(event)

        elif isinstance(event, EncryptionSettings):
            self.encryption = event
            await self._save()

        elif isinstance(event, Member) and event.left:
            self.members.discard(event.state_key)
            await self.client.e2e.drop_outbound_group_sessions(self.id)
            await self._save()

        elif isinstance(event, Member):
            self.members.add(event.state_key)
            await self._save()


    async def send(
        self, event: RoomEvent, transaction_id: Optional[str] = None,
    ) -> str:

        if self.encryption and not isinstance(event, Megolm):
            event = await self.client.e2e.encrypt_room_event(
                self.id, self.members, self.encryption, event,
            )

        if not event.type:
            raise TypeError(f"{event} is missing a type")

        tx_id = transaction_id if transaction_id else str(uuid4())
        path  = [*self.client.api, "rooms", self.id, "send", event.type, tx_id]

        if isinstance(event, StateEvent):
            path = [*self.client.api, "rooms", self.id, "state", event.type]
            if event.state_key:
                path.append(event.state_key)

        result = await self.client.send_json(
            "PUT", path, body=event.matrix["content"],
        )
        return result["event_id"]


from ...base_client import Client
from .timeline import Timeline

Room.update_forward_refs()
