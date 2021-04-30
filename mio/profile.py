# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional, Union

from aiopath import AsyncPath

from .core.data import Parent, Runtime
from .core.files import SeekableIO
from .core.ids import MXC
from .core.transfer import TransferUpdateCallback
from .core.utils import MaybeCoro, make_awaitable
from .media.file import Media
from .module import JSONClientModule
from .rooms.contents.users import Member
from .rooms.events import StateBase

if TYPE_CHECKING:
    from .client import Client

Callback = Callable[["Profile"], MaybeCoro]


@dataclass
class Profile(JSONClientModule):
    client:   Parent["Client"]            = field(repr=False)
    name:     Optional[str]               = None
    avatar:   Optional[MXC]               = None
    callback: Runtime[Optional[Callback]] = None


    @property
    def path(self) -> AsyncPath:
        return self.client.path.parent / "profile.json"


    async def set_name(self, name: str) -> None:
        url = self.net.api / "profile" / self.client.user_id / "displayname"
        await self.net.put(url, {"displayname": name})


    async def set_avatar(self, avatar: MXC) -> None:
        url = self.net.api / "profile" / self.client.user_id / "avatar_url"
        await self.net.put(url, {"avatar_url": str(avatar)})


    async def set_avatar_from_data(
        self,
        data:      SeekableIO,
        filename:  Optional[str]          = None,
        on_update: TransferUpdateCallback = None,
    ) -> Media:

        media = await self.client.media.upload(data, filename, on_update)
        await self.set_avatar(await media.last_mxc)
        return media


    async def set_avatar_from_path(
        self, path: Union[Path, str], on_update: TransferUpdateCallback = None,
    ) -> Media:

        media = await self.client.media.upload_from_path(path, on_update)
        await self.set_avatar(await media.last_mxc)
        return media


    async def _query(self) -> None:
        url   = self.net.api / "profile" / self.client.user_id
        reply = await self.net.get(url)

        previous    = (self.name, self.avatar)
        self.name   = reply.json.get("displayname")
        avatar      = reply.json.get("avatar_url")
        self.avatar = MXC(avatar) if avatar else None

        if (self.name, self.avatar) != previous:
            if self.callback:
                await make_awaitable(self.callback(self))

            await self.save()


    async def _update_on_sync(self, *member_evs: StateBase[Member]) -> None:
        # TODO: update from presence events?
        for event in member_evs:
            about_us      = event.state_key == self.client.user_id
            name_change   = event.content.display_name != self.name
            avatar_change = event.content.avatar_url != self.avatar

            if about_us and (name_change or avatar_change):
                # Don't trust the events themselves to update our global
                # profile, as name and avatar can be overriden per-room
                await self._query()
                return
        else:
            if not self.client.rooms:
                await self._query()
