from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, List, Tuple

from ..core.callbacks import CallbackGroup, Callbacks, EventCallbacks
from ..core.data import JSONFile, Parent, Runtime
from ..core.types import RoomAlias, RoomId, UserId
from .state import RoomState
from .timeline import Timeline

if TYPE_CHECKING:
    from ..client import Client


@dataclass
class Room(JSONFile, EventCallbacks):
    client:  Parent["Client"] = field(repr=False)
    id:      RoomId

    # Set by Sync.handle_sync
    invited:              bool               = False
    left:                 bool               = False
    summary_heroes:       Tuple[UserId, ...] = ()
    summary_joined:       int                = 0
    summary_invited:      int                = 0
    unread_notifications: int                = 0
    unread_highlights:    int                = 0

    timeline: Runtime[Timeline]  = field(init=False, repr=False)
    state:    Runtime[RoomState] = field(init=False, repr=False)


    def __post_init__(self) -> None:
        self.timeline = Timeline(self)
        self.state    = RoomState(self)
        super().__post_init__()


    @property
    def path(self) -> Path:
        return self.client.path.parent / "rooms" / self.id / "room.json"


    async def load(self) -> "Room":
        await super().load()
        await self.timeline.load()
        await self.state.load()
        return self


    async def create_alias(self, alias: RoomAlias) -> None:
        await self.client.send_json(
            method = "PUT",
            path   = [*self.client.api, "directory", "room", alias],
            body   = {"room_id": self.id},
        )


    async def leave(self) -> None:
        path = [*self.client.api, "rooms", self.id, "leave"]
        await self.client.send_json("POST", path)


    def _callbacks(self) -> Callbacks:
        return self.client.rooms.callbacks


    def _callback_groups(self) -> List[CallbackGroup]:
        return self.client.rooms.callback_groups
