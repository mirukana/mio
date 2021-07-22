# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Dict, Optional, Tuple

from ..core.contents import EventContentType
from ..core.data import Parent
from ..core.ids import MXC, EventId, UserId
from ..core.utils import remove_none
from .contents.messages import Message
from .contents.settings import Creation
from .contents.users import Member
from .events import StateBase

if TYPE_CHECKING:
    from .room import Room

@dataclass
class RoomUser:
    room:  Parent["Room"]    = field(repr=False)
    state: StateBase[Member] = field(repr=False)


    def __post_init__(self) -> None:
        self.user_id  # fail early if user ID is invalid


    def __repr__(self) -> str:
        props = ", ".join((
            f"{name}={getattr(self, name)!r}"
            for name, cls_attr in type(self).__dict__.items()
            if isinstance(cls_attr, property)
        ))
        return "%s(%s)" % (type(self).__name__, props)


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
        return self.room.state.power_levels.user_level(self.user_id)


    @property
    def invited(self) -> bool:
        return self.state.content.membership is Member.Kind.invite


    @property
    def joined(self) -> bool:
        return self.state.content.membership is Member.Kind.join


    @property
    def left(self) -> bool:
        return self.state.content.membership is Member.Kind.leave


    @property
    def banned(self) -> bool:
        return self.state.content.membership is Member.Kind.ban


    @property
    def invited_by(self) -> Optional[UserId]:
        return self.state.sender if self.invited else None


    @property
    def kicked_by(self) -> Optional[UserId]:
        sender = self.state.sender
        return sender if self.left and sender != self.user_id else None


    @property
    def banned_by(self) -> Optional[UserId]:
        return self.state.sender if self.banned else None


    @property
    def membership_reason(self) -> Optional[str]:
        return self.state.content.reason


    @property
    def typing(self) -> bool:
        return self.user_id in self.room.typing


    @property
    def receipts(self) -> Dict[str, Tuple[EventId, Optional[datetime]]]:
        return self.room.receipts_by_user.get(self.user_id, {})


    def can_send_message(self, event_type: EventContentType = Message) -> bool:
        min_level = self.room.state.power_levels.message_min_level(event_type)
        return self.joined and self.power_level >= min_level


    def can_send_state(self, event_type: EventContentType) -> bool:
        bad_type  = isinstance(event_type, Creation)  # can never be changed
        min_level = self.room.state.power_levels.state_min_level(event_type)
        return self.joined and not bad_type and self.power_level >= min_level


    def can_trigger_notification(self, kind: str = "room") -> bool:
        min_level = self.room.state.power_levels.notification_min_level(kind)
        return self.joined and self.power_level >= min_level


    def can_invite(self, user_id: Optional[UserId] = None) -> bool:
        user_ok = not user_id or (
            user_id not in self.room.state.members and
            user_id not in self.room.state.banned
        )
        min_level = self.room.state.power_levels.invite
        return self.joined and user_ok and self.power_level >= min_level


    def can_redact(self, sender_id: Optional[UserId] = None) -> bool:
        return self._can_act(sender_id, self.room.state.power_levels.redact)


    def can_kick(self, user_id: Optional[UserId] = None) -> bool:
        state         = self.room.state
        membership_ok = user_id in state.invitees or user_id in state.members
        ok            = not user_id or membership_ok
        return ok and self._can_act(user_id, self.room.state.power_levels.kick)


    def can_ban(self, user_id: Optional[UserId] = None) -> bool:
        ok = not user_id or user_id not in self.room.state.banned
        return ok and self._can_act(
            user_id, self.room.state.power_levels.ban, self_always_ok=False,
        )


    def can_unban(self, user_id: Optional[UserId] = None) -> bool:
        ok = not user_id or user_id in self.room.state.banned
        return ok and self._can_act(
            user_id, self.room.state.power_levels.ban, self_always_ok=False,
        )


    async def kick(self, reason: Optional[str] = None) -> None:
        await self.room.client.net.post(
            self.room.client.net.api / "rooms" / self.room.id / "kick",
            remove_none({"user_id": self.user_id, "reason": reason}),
        )


    async def ban(self, reason: Optional[str] = None) -> None:
        await self.room.client.net.post(
            self.room.client.net.api / "rooms" / self.room.id / "ban",
            remove_none({"user_id": self.user_id, "reason": reason}),
        )


    async def unban(self, reason: Optional[str] = None) -> None:
        await self.room.client.net.post(
            self.room.client.net.api / "rooms" / self.room.id / "unban",
            remove_none({"user_id": self.user_id, "reason": reason}),
        )


    def _can_act(
        self,
        target:           Optional[UserId],
        absolute_minimum: int,
        self_always_ok:   bool = True,
    ) -> bool:

        if self.joined and self_always_ok and target == self.user_id:
            return True

        if not self.joined or self.power_level < absolute_minimum:
            return False

        if not target:
            return True

        target_level = self.room.state.power_levels.user_level(target)
        return self.power_level > target_level
