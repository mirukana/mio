from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Tuple

from ...events.base_events import Event, StateKind, TimelineEvent
from ...events.room_state import Member
from ...typing import RoomId, UserId
from ...utils import JSONFile, Runtime
from .state import RoomState
from .timeline import Timeline

if TYPE_CHECKING:
    from ...base_client import Client



@dataclass
class Room(JSONFile):
    client:  Runtime["Client"] = field(repr=False)
    id:      RoomId

    # Set by Synchronizer.handle_sync
    invited:              bool               = False
    left:                 bool               = False
    summary_heroes:       Tuple[UserId, ...] = ()
    summary_joined:       int                = 0
    summary_invited:      int                = 0
    unread_notifications: int                = 0
    unread_highlights:    int                = 0

    timeline: Runtime[Timeline]  = field(init=False, repr=False)
    state:    Runtime[RoomState] = field(init=False, repr=False)


    async def __ainit__(self) -> None:
        self.timeline = \
            await Timeline.load(self.path.parent / "timeline.json", room=self)

        self.state = \
            await RoomState.load(self.path.parent / "state.json", room=self)


    async def handle_event(self, event: Event) -> None:
        # TODO: handle_event**s** function that only saves at the end

        if isinstance(event, TimelineEvent):
            await self.timeline.register_events(event)
        elif isinstance(event, StateKind):
            await self.state.register(event)

        content = event.content

        if isinstance(content, Member) and content.left:
            await self.client.e2e.drop_outbound_group_sessions(self.id)
            await self.save()
