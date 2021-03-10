from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Optional

from ...client_modules.encryption.events import EncryptionSettings
from ...events.base_events import (
    Content, InvitedRoomStateEvent, StateEvent, StateKind,
)
from ...events.room_state import Member
from ...typing import UserId
from ...utils import Frozen, JSONFile, Map, Parent

if TYPE_CHECKING:
    from .room import Room


@dataclass
class RoomState(JSONFile, Frozen, Map[str, Dict[str, StateKind]]):
    loaders = {
        **JSONFile.loaders,  # type: ignore
        StateKind: lambda v, parent: (  # type: ignore
            StateEvent if "event_id" in v else InvitedRoomStateEvent
        ).from_dict(v, parent),
    }

    room: Parent["Room"] = field(repr=False)

    # {event.type: {event.state_key: event}}
    _data: Dict[str, Dict[str, StateKind]] = field(default_factory=dict)


    @property
    def encryption(self) -> Optional[StateKind[EncryptionSettings]]:
        return self.get(EncryptionSettings.type, {}).get("")


    @classmethod
    def get_path(cls, parent: "Room", **kwargs) -> Path:
        return parent.path.parent / "state.json"


    def users(
        self,
        invitees: bool = True,
        joined:   bool = True,
        left:     bool = True,
        banned:   bool = True,
    ) -> Dict[UserId, StateKind[Member]]:

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
    def invitees(self) -> Dict[UserId, StateKind[Member]]:
        return self.users(joined=False, left=False, banned=False)


    @property
    def members(self) -> Dict[UserId, StateKind[Member]]:
        return self.users(invitees=False, left=False, banned=False)


    @property
    def dropouts(self) -> Dict[UserId, StateKind[Member]]:
        return self.users(invitees=False, joined=False, banned=False)


    @property
    def banned(self) -> Dict[UserId, StateKind[Member]]:
        return self.users(invitees=False, joined=False, left=False)


    @property
    def us(self) -> Optional[StateKind[Member]]:
        return self.users().get(self.room.client.user_id)


    @property
    def inviter(self) -> Optional[UserId]:
        invite  = Member.Membership.invite
        invited = self.us and self.us.content.membership == invite
        return self.us.sender if self.us and invited else None


    async def register(self, event: StateKind) -> None:
        assert event.type
        self._data.setdefault(event.type, {})[event.state_key] = event
        await self.save()


    async def send(self, content: Content, state_key: str = "") -> str:
        assert content.type
        room = self.room
        path = [*room.client.api, "rooms", room.id, "state", content.type]

        if state_key:
            path.append(state_key)

        result = await room.client.send_json("PUT", path, body=content.dict)
        return result["event_id"]
