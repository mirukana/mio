from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from ...events import Event
from ..encryption.events import Encryption


@dataclass
class Room:
    id:         str
    encryption: Optional[Encryption] = None
    events:     List[Event]          = field(default_factory=list, repr=False)

    async def handle_event(self, event: Event) -> None:
        if isinstance(event, Encryption):
            self.encryption = event

        self.events.append(event)


    async def send(
        self, event: Event, transaction_id: Optional[str] = None,
    ) -> str:
        pass


@dataclass
class InvitedRoom(Room):
    inviter: Optional[str] = None


@dataclass
class JoinedRoom(Room):
    summary_heroes:       Tuple[str, ...] = ()
    summary_joined:       int             = 0
    summary_invited:      int             = 0
    unread_notifications: int             = 0
    unread_highlights:    int             = 0
    scrollback_token:     Optional[str]   = None


@dataclass
class LeftRoom(Room):
    pass
