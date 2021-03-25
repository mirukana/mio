from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Optional

from ..core.contents import EventContent
from ..core.data import JSONFile, Map, Parent
from ..core.types import UserId
from .contents.settings import Encryption
from .contents.users import Member
from .events import InvitedRoomStateEvent, StateBase, StateEvent

if TYPE_CHECKING:
    from .room import Room


@dataclass
class RoomState(JSONFile, Map[str, Dict[str, StateBase]]):
    loaders = {
        **JSONFile.loaders,  # type: ignore

        StateBase: lambda v, parent: (  # type: ignore
            StateEvent if "event_id" in v else InvitedRoomStateEvent
        ).from_dict(v, parent),
    }

    room: Parent["Room"] = field(repr=False)

    # {event.type: {event.state_key: event}}
    _data: Dict[str, Dict[str, StateBase]] = field(default_factory=dict)


    async def load(self) -> "RoomState":
        await super().load()
        await self._register(*[
            ev for state_keys in self.values() for ev in state_keys.values()
        ])
        return self


    @property
    def path(self) -> Path:
        return self.room.client.path.parent / "state.json"


    @property
    def encryption(self) -> Optional[StateBase[Encryption]]:
        return self.get(Encryption.type, {}).get("")


    def users(
        self,
        invitees: bool = True,
        joined:   bool = True,
        left:     bool = True,
        banned:   bool = True,
    ) -> Dict[UserId, StateBase[Member]]:

        if invitees and joined and left and banned:
            return self.get(Member.type, {})  # type: ignore

        include = {
            Member.Kind.invite: invitees,
            Member.Kind.join: joined,
            Member.Kind.leave: left,
            Member.Kind.ban: banned,
        }

        return {
            UserId(uid): event
            for uid, event in self.get(Member.type, {}).items()
            if include[event.content.membership]
        }


    @property
    def invitees(self) -> Dict[UserId, StateBase[Member]]:
        return self.users(joined=False, left=False, banned=False)


    @property
    def members(self) -> Dict[UserId, StateBase[Member]]:
        return self.users(invitees=False, left=False, banned=False)


    @property
    def leavers(self) -> Dict[UserId, StateBase[Member]]:
        return self.users(invitees=False, joined=False, banned=False)


    @property
    def banned(self) -> Dict[UserId, StateBase[Member]]:
        return self.users(invitees=False, joined=False, left=False)


    @property
    def us(self) -> Optional[StateBase[Member]]:
        return self.users().get(self.room.client.user_id)


    @property
    def inviter(self) -> Optional[UserId]:
        invited = self.us and self.us.content.membership == Member.Kind.invite
        return self.us.sender if self.us and invited else None


    async def send(self, content: EventContent, state_key: str = "") -> str:
        assert content.type
        room = self.room
        path = [*room.client.api, "rooms", room.id, "state", content.type]

        if state_key:
            path.append(state_key)

        result = await room.client.send_json("PUT", path, body=content.dict)
        return result["event_id"]


    async def _register(self, *events: StateBase) -> None:
        for event in events:
            assert event.type
            self._data.setdefault(event.type, {})[event.state_key] = event
            await self.room._call_callbacks(event)

        await self.save()
