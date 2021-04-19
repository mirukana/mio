from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Optional

from aiopath import AsyncPath

from .core.callbacks import MaybeCoro
from .core.data import Parent, Runtime
from .core.types import MXC
from .core.utils import make_awaitable
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
        url = self.client.api / "profile" / self.client.user_id / "displayname"
        await self.client.send_json("PUT", url, {"displayname": name})


    async def set_avatar(self, avatar: MXC) -> None:
        url = self.client.api / "profile" / self.client.user_id / "avatar_url"
        await self.client.send_json("PUT", url, {"avatar_url": str(avatar)})


    async def _query(self) -> None:
        url    = self.client.api / "profile" / self.client.user_id
        result = await self.client.send_json("GET", url)

        previous    = (self.name, self.avatar)
        self.name   = result.get("displayname")
        avatar      = result.get("avatar_url")
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
