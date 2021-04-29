# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

import shutil
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Optional, Set, Tuple

from aiopath import AsyncPath

from ..core.callbacks import CallbackGroup, Callbacks, EventCallbacks
from ..core.data import JSONFile, Parent, Runtime
from ..core.files import encode_name
from ..core.ids import RoomAlias, RoomId, UserId
from ..core.utils import remove_none
from ..net.net import Network
from .state import RoomState
from .timeline import Timeline

if TYPE_CHECKING:
    from ..client import Client


@dataclass
class Room(JSONFile, EventCallbacks):
    client:  Parent["Client"] = field(repr=False)
    id:      RoomId

    # Set by Sync.handle_sync and default callbacks
    invited:              bool               = False
    left:                 bool               = False
    typing:               Set[UserId]        = field(default_factory=set)
    summary_heroes:       Tuple[UserId, ...] = ()
    summary_joined:       int                = 0
    summary_invited:      int                = 0
    unread_notifications: int                = 0
    unread_highlights:    int                = 0

    timeline: Runtime[Timeline]  = field(init=False, repr=False)
    state:    Runtime[RoomState] = field(init=False, repr=False)


    def __post_init__(self) -> None:
        self.client.rooms.forgotten.discard(self.id)

        self.timeline = Timeline(self)
        self.state    = RoomState(self)

        super().__post_init__()


    @property
    def path(self) -> AsyncPath:
        room_id = encode_name(self.id)
        return self.client.path.parent / "rooms" / room_id / "room.json"


    @property
    def net(self) -> Network:
        return self.client.net


    async def load(self) -> "Room":
        await super().load()
        await self.timeline.load()
        await self.state.load()
        return self


    async def start_typing(self, timeout: int = 5) -> None:
        await self.net.put(
            self.net.api / "rooms" / self.id / "typing" / self.client.user_id,
            {"typing": True, "timeout": int(timeout * 1000)},
        )


    async def stop_typing(self) -> None:
        await self.net.put(
            self.net.api / "rooms" / self.id / "typing" / self.client.user_id,
            {"typing": False},
        )


    async def create_alias(self, alias: RoomAlias) -> None:
        data = {"room_id": self.id}
        await self.net.put(self.net.api / "directory" / "room" / alias, data)


    async def invite(
        self, user_id: UserId, reason: Optional[str] = None,
    ) -> None:
        await self.net.post(
            self.net.api / "rooms" / self.id / "invite",
            remove_none({"user_id": user_id, "reason": reason}),
        )


    async def leave(self, reason: Optional[str] = None) -> None:
        await self.net.post(
            self.net.api / "rooms" / self.id / "leave",
            remove_none({"reason": reason}),
        )


    async def forget(self, leave_reason: Optional[str] = None) -> None:
        # Prevent a sync from occuring AFTER leaving room, but BEFORE having
        # marked it as forgotten. We will get a "we left" event on next sync,
        # which we must ignore if we know we forgot the room.
        with self.client.sync.pause():
            if not self.left:
                await self.leave(leave_reason)

            await self.net.post(self.net.api / "rooms" / self.id / "forget")

            self.left = True
            self.client.rooms._data.pop(self.id, None)
            self.client.rooms.forgotten.add(self.id)

        shutil.rmtree(self.path.parent)


    def _callbacks(self) -> Callbacks:
        return self.client.rooms.callbacks


    def _callback_groups(self) -> List[CallbackGroup]:
        return self.client.rooms.callback_groups
