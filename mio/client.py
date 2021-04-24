from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

from aiopath import AsyncPath
from filelock import FileLock
from yarl import URL

from .auth import Auth
from .core.data import JSONFile, Runtime
from .core.ids import UserId
from .core.utils import get_logger
from .devices.devices import Devices
from .e2e.e2e import E2E
from .media.store import MediaStore
from .module import ClientModule
from .net.net import Network
from .profile import Profile
from .rooms.rooms import Rooms
from .sync import Sync

LOG = get_logger()


@dataclass
class Client(JSONFile):
    base_dir:     Runtime[Union[Path, str]]
    server:       Union[URL, str] = ""
    device_id:    str             = ""
    user_id:      UserId          = ""  # type: ignore
    access_token: str             = ""

    net:     Runtime[Network]    = field(init=False, repr=False)
    auth:    Runtime[Auth]       = field(init=False, repr=False)
    profile: Runtime[Profile]    = field(init=False, repr=False)
    rooms:   Runtime[Rooms]      = field(init=False, repr=False)
    sync:    Runtime[Sync]       = field(init=False, repr=False)
    e2e:     Runtime[E2E]        = field(init=False, repr=False)
    devices: Runtime[Devices]    = field(init=False, repr=False)
    media:   Runtime[MediaStore] = field(init=False, repr=False)

    _lock: Runtime[Optional[FileLock]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.net     = Network(self)
        self.auth    = Auth(self)
        self.profile = Profile(self)
        self.rooms   = Rooms(self)
        self.sync    = Sync(self)
        self.e2e     = E2E(self)
        self.devices = Devices(self)
        self.media   = MediaStore(self)
        self._lock   = None
        super().__post_init__()


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


    def _acquire_lock(self) -> None:
        self._lock = FileLock(str(Path(self.base_dir) / ".lock"))
        self._lock.acquire(timeout=1)
