from dataclasses import dataclass, field
from enum import Enum
from typing import (
    TYPE_CHECKING, DefaultDict, Dict, List, Optional, Sequence, Tuple, Union,
)

from ..core.callbacks import CallbackGroup, Callbacks
from ..core.contents import EventContent
from ..core.data import IndexableMap, Parent, Runtime
from ..core.types import RoomAlias, RoomId
from ..core.utils import remove_none
from ..module import ClientModule
from .contents.users import Member
from .events import StateBase, TimelineEvent
from .room import Room

if TYPE_CHECKING:
    from ..client import Client


class MioRoomCallbacks(CallbackGroup):
    async def on_timeline(self, room: Room, event: TimelineEvent) -> None:
        await room.timeline.register_events(event)

    async def on_state(self, room: Room, event: StateBase) -> None:
        await room.state.register(event)

    async def on_leave(self, room: Room, event: StateBase[Member]) -> None:
        if event.content.left:
            await room.client.e2e.drop_outbound_group_session(room.id)


@dataclass
class Rooms(ClientModule, IndexableMap[RoomId, Room]):
    client:    Parent["Client"]          = field(repr=False)
    _data:     Dict[RoomId, Room]        = field(default_factory=dict)

    callbacks: Runtime[Callbacks] = field(
        init=False, repr=False, default_factory=lambda: DefaultDict(list),
    )

    callback_groups: Runtime[List["CallbackGroup"]] = field(
        init=False, repr=False, default_factory=lambda: [MioRoomCallbacks()],
    )


    @classmethod
    async def load(cls, parent: "Client") -> "Rooms":
        rooms = cls(parent)

        for room_dir in (parent.path.parent / "rooms").glob("!*"):
            id              = RoomId(room_dir.name)
            rooms._data[id] = await Room.load(parent, id=id)

        return rooms


    @property
    def invited(self) -> Dict[RoomId, Room]:
        return {k: v for k, v in self.items() if v.invited and not v.left}


    @property
    def joined(self) -> Dict[RoomId, Room]:
        return {k: v for k, v in self.items() if not v.invited and not v.left}


    @property
    def left(self) -> Dict[RoomId, Room]:
        return {k: v for k, v in self.items() if v.left}


    async def create(
        self,
        name:              Optional[str]                      = None,
        topic:             Optional[str]                      = None,
        alias:             Optional[str]                      = None,
        invitees:          Sequence[str]                      = (),
        public:            bool                               = False,
        direct_chat:       bool                               = False,
        federate:          bool                               = True,
        version:           Optional[str]                      = None,
        preset:            Optional["CreationPreset"]         = None,
        additional_states: Sequence[Tuple[str, EventContent]] = (),
    ) -> RoomId:

        if alias and isinstance(alias, RoomAlias):
            alias = alias.split(":")[0][0:]

        body = {
            "visibility": "public" if public else "private",
            "creation_content": {"m.federate": federate},
            "is_direct": direct_chat,
            "room_alias_name": alias,
            "name": name,
            "topic": topic,
            "room_version": version,
            "preset": preset.value if preset else None,
            "invite": invitees,
            "initial_state": [
                {"type": cnt.type, "state_key": state_key, "content": cnt.dict}
                for state_key, cnt in additional_states
            ],
        }

        result = await self.client.send_json(
            "POST", [*self.client.api, "createRoom"], body=remove_none(body),
        )

        return result["room_id"]


    async def join(self, id_or_alias: Union[RoomId, RoomAlias]) -> RoomId:
        result = await self.client.send_json(
            "POST", [*self.client.api, "join", id_or_alias],
        )

        return result["room_id"]


class CreationPreset(Enum):
    """Room creation presets set default state events when creating a room.

    - `public`: anyone can join the room, except guests (unregistered users)
    - `private`: make the room invite-only and allow inviting guests
    - `private_trusted`: gives all members the same power level as the creator
    """

    public          = "public_chat"
    private         = "private_chat"
    private_trusted = "trusted_private_chat"
