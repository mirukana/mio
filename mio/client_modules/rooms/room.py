from __future__ import annotations

from typing import List, Optional, Set, Tuple
from uuid import uuid4

from pydantic import BaseModel

from ...events.base_events import Event, RoomEvent, StateEvent
from ...events.room_state import Member
from ...typing import RoomId, UserId
from ..encryption.events import EncryptionSettings, Megolm


class Room(BaseModel):
    client:     Client
    id:         RoomId
    encryption: Optional[EncryptionSettings] = None
    members:    Set[UserId]                  = set()

    events: List[Event] = []

    async def handle_event(self, event: Event) -> None:
        if isinstance(event, EncryptionSettings):
            self.encryption = event

        elif isinstance(event, Member) and event.left:
            self.members.discard(event.state_key)
            await self.client.e2e.drop_outbound_group_sessions(self.id)

        elif isinstance(event, Member):
            self.members.add(event.state_key)

        self.events.append(event)

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


class InvitedRoom(Room):
    inviter: Optional[str] = None


class JoinedRoom(Room):
    summary_heroes:       Tuple[str, ...] = ()
    summary_joined:       int             = 0
    summary_invited:      int             = 0
    unread_notifications: int             = 0
    unread_highlights:    int             = 0
    scrollback_token:     Optional[str]   = None


class LeftRoom(Room):
    pass


from ...base_client import Client

Room.update_forward_refs()
InvitedRoom.update_forward_refs()
JoinedRoom.update_forward_refs()
LeftRoom.update_forward_refs()
