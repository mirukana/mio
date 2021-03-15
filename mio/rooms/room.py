from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Tuple

from ..core.contents import EventContent
from ..core.data import JSONFile, Parent, Runtime
from ..core.events import Event
from ..core.types import RoomAlias, RoomId, UserId
from ..core.utils import make_awaitable
from .contents.users import Member
from .events import StateBase, TimelineEvent
from .state import RoomState
from .timeline import Timeline

if TYPE_CHECKING:
    from ..client import Client



@dataclass
class Room(JSONFile):
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


    @property
    def path(self) -> Path:
        return self.get_path(self.parent, id=self.id)  # type: ignore


    @classmethod
    def get_path(cls, parent: "Client", **kwargs) -> Path:
        return parent.path.parent / "rooms" / kwargs["id"] / "room.json"


    async def __ainit__(self) -> None:
        self.timeline = await Timeline.load(self)
        self.state    = await RoomState.load(self)
        await self.save()


    async def create_alias(self, alias: RoomAlias) -> None:
        await self.client.send_json(
            method = "PUT",
            path   = [*self.client.api, "directory", "room", alias],
            body   = {"room_id": self.id},
        )


    async def handle_event(self, event: Event) -> None:
        # TODO: handle_event**s** function that only saves at the end

        if isinstance(event, TimelineEvent):
            await self.timeline.register_events(event)
        elif isinstance(event, StateBase):
            await self.state.register(event)

        content = event.content

        if isinstance(content, Member) and content.left:
            await self.client.e2e.drop_outbound_group_sessions(self.id)
            await self.save()

        for annotation, callbacks in self.client.rooms.callbacks.items():
            ann_type = getattr(annotation, "__origin__", annotation)

            if issubclass(ann_type, EventContent):
                event_type   = Event
                content_type = ann_type
            else:
                event_type   = ann_type
                default      = (EventContent,)
                content_type = getattr(annotation, "__args__", default)[0]

            event_matches   = isinstance(event, event_type)
            content_matches = isinstance(event.content, content_type)

            if event_matches and content_matches:
                for cb in callbacks:
                    await make_awaitable(cb(self, event))
