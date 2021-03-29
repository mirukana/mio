from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from ..core.data import Parent
from ..core.types import MXC, UserId
from ..core.utils import remove_none
from .contents.users import Member
from .events import StateBase

if TYPE_CHECKING:
    from .room import Room


@dataclass
class RoomUser:
    room:  Parent["Room"]    = field(repr=False)
    state: StateBase[Member] = field(repr=False)


    @property
    def user_id(self) -> UserId:
        return UserId(self.state.state_key)


    @property
    def display_name(self) -> Optional[str]:
        return self.state.content.display_name


    @property
    def unique_name(self) -> str:
        if self.display_name is None:
            return self.user_id

        if len(self.room.state._display_names[self.display_name]) < 2:
            return self.display_name

        return f"{self.display_name} ({self.user_id})"


    @property
    def avatar_url(self) -> Optional[MXC]:
        return self.state.content.avatar_url


    @property
    def power_level(self) -> int:
        levels = self.room.state.power_levels
        return levels.users.get(self.user_id, levels.users_default)


    @property
    def inviter(self) -> Optional[UserId]:
        invited = self.state.content.membership is Member.Kind.invite
        return self.state.sender if invited else None


    @property
    def joined(self) -> bool:
        return self.state.content.membership is Member.Kind.join


    @property
    def left(self) -> bool:
        return self.state.content.membership is Member.Kind.leave


    @property
    def kicked_by(self) -> Optional[UserId]:
        sender = self.state.sender
        return sender if self.left and sender != self.user_id else None


    @property
    def banned_by(self) -> Optional[UserId]:
        banned = self.state.content.membership is Member.Kind.ban
        return self.state.sender if banned else None


    @property
    def membership_reason(self) -> Optional[str]:
        return self.state.content.reason


    @property
    def typing(self) -> bool:
        return self.user_id in self.room.typing


    async def kick(self, reason: Optional[str] = None) -> None:
        await self.room.client.send_json(
            "POST",
            self.room.client.api / "rooms" / self.room.id / "kick",
            remove_none({"user_id": self.user_id, "reason": reason}),
        )


    async def ban(self, reason: Optional[str] = None) -> None:
        await self.room.client.send_json(
            "POST",
            self.room.client.api / "rooms" / self.room.id / "ban",
            remove_none({"user_id": self.user_id, "reason": reason}),
        )


    async def unban(self, reason: Optional[str] = None) -> None:
        await self.room.client.send_json(
            "POST",
            self.room.client.api / "rooms" / self.room.id / "unban",
            remove_none({"user_id": self.user_id, "reason": reason}),
        )
