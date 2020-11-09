from dataclasses import dataclass
from typing import Optional, Tuple

from ...events import Event


@dataclass
class Room:
    id: str

    async def handle_event(self, event: Event) -> None:
        print(repr(event))


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
