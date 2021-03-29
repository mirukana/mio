from dataclasses import dataclass, field
from enum import Enum
from typing import (
    TYPE_CHECKING, DefaultDict, Dict, List, Optional, Sequence, Set, Tuple,
    Union,
)

from ..core.callbacks import CallbackGroup, Callbacks
from ..core.contents import EventContent
from ..core.data import IndexableMap, Parent, Runtime
from ..core.types import RoomAlias, RoomId, UserId
from ..core.utils import remove_none
from ..module import ClientModule
from .contents.users import Member
from .events import StateBase, StateEvent
from .room import Room
from .user import RoomUser

if TYPE_CHECKING:
    from ..client import Client


class MioRoomCallbacks(CallbackGroup):
    async def on_member(self, room: Room, event: StateBase[Member]) -> None:
        content  = event.content
        user_id  = UserId(event.state_key)
        previous = event.previous if isinstance(event, StateEvent) else None
        places   = {
            Member.Kind.invite: room.state.invitees,
            Member.Kind.join:   room.state.members,
            Member.Kind.leave:  room.state.leavers,
            Member.Kind.ban:    room.state.banned,
        }

        for place in places.values():
            room_member = place.pop(user_id, None)

            if room_member:
                room_member.state = event
                break
        else:
            room_member = RoomUser(room, event)

        places[content.membership][user_id] = room_member

        if previous and previous.display_name:
            room.state._display_names[previous.display_name].discard(user_id)

        if content.absent and content.display_name:
            room.state._display_names[content.display_name].discard(user_id)
        elif content.display_name:
            room.state._display_names[content.display_name].add(user_id)

        if not event.from_disk and content.absent:
            await room.client._e2e.drop_outbound_group_session(room.id)


@dataclass
class Rooms(ClientModule, IndexableMap[RoomId, Room]):
    client: Parent["Client"]   = field(repr=False)
    _data:  Dict[RoomId, Room] = field(default_factory=dict)

    callbacks: Runtime[Callbacks] = field(
        default_factory=lambda: DefaultDict(list),
    )

    callback_groups: Runtime[List["CallbackGroup"]] = field(
        default_factory=lambda: [MioRoomCallbacks()],
    )

    forgotten: Runtime[Set[RoomId]] = field(default_factory=set)


    @property
    def invited(self) -> Dict[RoomId, Room]:
        return {k: v for k, v in self.items() if v.invited and not v.left}


    @property
    def joined(self) -> Dict[RoomId, Room]:
        return {k: v for k, v in self.items() if not v.invited and not v.left}


    @property
    def left(self) -> Dict[RoomId, Room]:
        return {k: v for k, v in self.items() if v.left}


    async def load(self) -> "Rooms":
        for room_dir in (self.client.path.parent / "rooms").glob("!*"):
            id             = RoomId(room_dir.name)
            self._data[id] = await Room(self.client, id=id).load()

        return self


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
            "POST", self.client.api / "createRoom", remove_none(body),
        )

        return result["room_id"]


    async def join(self, id_or_alias: Union[RoomId, RoomAlias]) -> RoomId:
        url    = self.client.api / "join" / id_or_alias
        result = await self.client.send_json("POST", url)
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
