from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Optional

from ...core.contents import EventContent
from ...core.data import JSONFile, Map, Parent
from ...core.types import UserId
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


    @property
    def encryption(self) -> Optional[StateBase[Encryption]]:
        return self.get(Encryption.type, {}).get("")


    @classmethod
    def get_path(cls, parent: "Room", **kwargs) -> Path:
        return parent.path.parent / "state.json"


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
            Member.Membership.invite: invitees,
            Member.Membership.join: joined,
            Member.Membership.leave: left,
            Member.Membership.ban: banned,
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
        invite  = Member.Membership.invite
        invited = self.us and self.us.content.membership == invite
        return self.us.sender if self.us and invited else None


    async def register(self, event: StateBase) -> None:
        assert event.type
        self._data.setdefault(event.type, {})[event.state_key] = event
        await self.save()


    async def send(self, content: EventContent, state_key: str = "") -> str:
        assert content.type
        room = self.room
        path = [*room.client.api, "rooms", room.id, "state", content.type]

        if state_key:
            path.append(state_key)

        result = await room.client.send_json("PUT", path, body=content.dict)
        return result["event_id"]
