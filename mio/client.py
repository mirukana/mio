# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

from aiopath import AsyncPath
from filelock import FileLock
from yarl import URL

from .account_data.account_data import AccountData
from .auth.auth import Auth
from .core.data import JSONFile, Runtime
from .core.ids import UserId
from .core.logging import MioLogger
from .devices.devices import Devices
from .e2e.e2e import E2E
from .filters import FilterStore
from .media.store import MediaStore
from .module import ClientModule
from .net.net import Network
from .profile import Profile
from .rooms.rooms import Rooms
from .sync import Sync


@dataclass
class Client(JSONFile, MioLogger):
    base_dir:     Runtime[Union[Path, str]]
    server:       Union[URL, str] = ""
    device_id:    str             = ""
    user_id:      UserId          = ""  # type: ignore
    access_token: str             = ""

    net:      Runtime[Network]     = field(init=False, repr=False)
    auth:     Runtime[Auth]        = field(init=False, repr=False)
    profile:  Runtime[Profile]     = field(init=False, repr=False)
    rooms:    Runtime[Rooms]       = field(init=False, repr=False)
    sync:     Runtime[Sync]        = field(init=False, repr=False)
    e2e:      Runtime[E2E]         = field(init=False, repr=False)
    devices:  Runtime[Devices]     = field(init=False, repr=False)
    media:    Runtime[MediaStore]  = field(init=False, repr=False)
    _filters: Runtime[FilterStore] = field(init=False, repr=False)

    _lock:       Runtime[Optional[FileLock]] = field(init=False, repr=False)
    _terminated: Runtime[bool]               = field(init=False, repr=False)


    def __post_init__(self) -> None:
        MioLogger.__post_init__(self)

        self.net          = Network(self)
        self.auth         = Auth(self)
        self.profile      = Profile(self)
        self.account_data = AccountData(self)
        self.rooms        = Rooms(self)
        self.sync         = Sync(self)
        self.e2e          = E2E(self)
        self.devices      = Devices(self)
        self.media        = MediaStore(self)
        self._filters     = FilterStore(self)

        self._lock       = None
        self._terminated = False

        JSONFile.__post_init__(self)


    async def __aenter__(self) -> "Client":
        return self


    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.terminate()


    def __del__(self) -> None:
        if self._lock:
            self._lock.release()


    @property
    def path(self) -> AsyncPath:
        return AsyncPath(self.base_dir) / "client.json"


    async def load(self, **base_dir_placeholders: str) -> "Client":
        self.base_dir = str(self.base_dir).format(**base_dir_placeholders)
        await super().load()

        self._acquire_lock()

        for attr in self.__dict__.values():
            if isinstance(attr, ClientModule):
                await attr.load()

        return self


    async def terminate(self) -> None:
        self.__del__()  # release lock
        await self.net.disconnect()
        self._terminated = True


    def _acquire_lock(self) -> None:
        self._lock = FileLock(str(Path(self.base_dir) / ".lock"))
        self._lock.acquire(timeout=1)
