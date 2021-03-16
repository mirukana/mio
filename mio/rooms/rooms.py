from dataclasses import dataclass, field
from enum import Enum
from inspect import signature
from typing import (
    TYPE_CHECKING, Awaitable, Callable, DefaultDict, Dict, List, Optional,
    Sequence, Set, Tuple, Type, Union,
)

from ..core.contents import EventContent
from ..core.data import IndexableMap, Parent, Runtime
from ..core.events import Event
from ..core.types import RoomAlias, RoomId
from ..core.utils import make_awaitable, remove_none
from ..module import ClientModule
from .room import Room

if TYPE_CHECKING:
    from ..client import Client

EventKey  = Union[Type[Event], Type[EventContent]]
Callbacks = Set[Callable[[Room, Event], Optional[Awaitable[None]]]]


@dataclass
class Rooms(ClientModule, IndexableMap[RoomId, Room]):
    client:    Parent["Client"]          = field(repr=False)
    _data:     Dict[RoomId, Room]        = field(default_factory=dict)

    callbacks: Runtime[Dict[EventKey, Callbacks]] = field(
        init=False, repr=False, default_factory=lambda: DefaultDict(set),
    )

    callback_groups: List["CallbackGroup"] = field(default_factory=list)


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


class CallbackGroup:
    async def __call__(self, room: Room, event: Event) -> None:
        for attr_name in dir(self):
            attr = getattr(self, attr_name)

            if not callable(attr) or attr_name.startswith("_"):
                continue

            params = list(signature(attr).parameters.values())

            if len(params) < 2:
                continue

            ann             = params[1].annotation
            event_type      = getattr(ann, "__origin__", ann)
            content_type    = getattr(ann, "__args__", (EventContent,))[0]
            event_matches   = isinstance(event, event_type)
            content_matches = isinstance(event.content, content_type)

            if event_matches and content_matches:
                await make_awaitable(attr(room, event))
