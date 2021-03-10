import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Type, Union

from .client_modules.authentication import Authentication
from .client_modules.encryption.encryption import Encryption
from .client_modules.rooms import Rooms
from .client_modules.synchronizer import Synchronization
from .typing import HttpUrl, UserId
from .utils import Frozen, JSONFileBase, Runtime, remove_none

if TYPE_CHECKING:
    from .client_modules import ClientModule


@dataclass
class Client(JSONFileBase, Frozen):
    base_dir:     Runtime[Path]
    server:       HttpUrl
    user_id:      UserId
    access_token: str
    device_id:    str

    auth:  Runtime[Authentication]  = field(init=False, repr=False)
    rooms: Runtime[Rooms]           = field(init=False, repr=False)
    sync:  Runtime[Synchronization] = field(init=False, repr=False)
    e2e:   Runtime[Encryption]      = field(init=False, repr=False)


    async def __ainit__(self) -> None:
        await self._load_module("auth", Authentication, "auth.json")
        await self._load_module("rooms", Rooms, "rooms")
        await self._load_module("sync", Synchronization, "sync.json")
        await self._load_module("e2e", Encryption, "e2e.json")
        await self.save()


    @property
    def api(self) -> List[str]:
        return [self.server, "_matrix", "client", "r0"]


    @property
    def path(self) -> Path:
        return self.base_dir / "client.json"


    @classmethod
    async def load(cls, base_dir: Union[Path, str]) -> "Client":
        data = await cls._read_file(Path(base_dir) / "client.json")
        return await cls.from_dict({**data, "base_dir": base_dir})


    @classmethod
    async def login(
        cls,
        base_dir: Union[Path, str],
        server:   HttpUrl,
        auth:     Dict[str, Any],
    ) -> "Client":
        """Login to a homeserver using a custom authentication dict.

        The `base_dir`, folder where client data will be stored, can contain
        `{user_id}` and `{device_id}` placeholders that will be
        automatically filled.
        """

        result = await cls.send_json(
            obj    = cls,
            method = "POST",
            path   = [server, "_matrix", "client", "r0", "login"],
            body   = auth,
        )

        base_dir = str(base_dir).format(
            user_id=result["user_id"], device_id=result["device_id"],
        )

        return await cls(
            base_dir     = Path(base_dir),
            server       = server,
            user_id      = result["user_id"],
            access_token = result["access_token"],
            device_id    = result["device_id"],
        )


    @classmethod
    async def login_password(
        cls,
        base_dir:            Union[Path, str],
        server:              HttpUrl,
        user:                str,
        password:            str,
        device_id:           Optional[str] = None,
        initial_device_name: str           = "mio",
    ) -> "Client":

        auth = {
            "type":                        "m.login.password",
            "user":                        user,
            "password":                    password,
            "device_id":                   device_id,
            "initial_device_display_name": initial_device_name,
        }

        return await cls.login(base_dir, server, remove_none(auth))


    @classmethod
    async def login_token(
        cls,
        base_dir:            Union[Path, str],
        server:              HttpUrl,
        user:                str,
        token:               str,
        device_id:           Optional[str] = None,
        initial_device_name: str           = "mio",
    ) -> "Client":

        auth = {
            "type":                        "m.login.token",
            "user":                        user,
            "token":                       token,
            "device_id":                   device_id,
            "initial_device_display_name": initial_device_name,
        }

        return await cls.login(base_dir, server, remove_none(auth))


    async def send(
        obj:        Union[Type["Client"], "Client"],
        method:     str,
        path:       List[str],
        parameters: Optional[Dict[str, Any]] = None,
        data:       Optional[bytes]          = None,
        headers:    Optional[Dict[str, Any]] = None,
    ) -> bytes:

        raise NotImplementedError()


    async def send_json(
        obj:        Union[Type["Client"], "Client"],
        method:     str,
        path:       List[str],
        parameters: Optional[Dict[str, Any]] = None,
        body:       Optional[Dict[str, Any]] = None,
        headers:    Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:

        cls    = type(obj) if isinstance(obj, Client) else obj
        data   = None if body is None else json.dumps(body).encode()
        result = await cls.send(obj, method, path, parameters, data, headers)
        return json.loads(result)


    async def _load_module(
        self, name: str, module: Type["ClientModule"], path_last_part: str,
    ) -> None:
        # Using __setattr__ like that because the dataclass is frozen
        setattr(self, name, await module.load(self))
