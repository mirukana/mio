import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, Union

from .client_modules.authentication import Authentication
from .client_modules.encryption.encryption import Encryption
from .client_modules.rooms import Rooms
from .client_modules.synchronizer import Synchronization
from .utils import AsyncInit, remove_none


@dataclass
class Client(AsyncInit):
    e2e_folder:   Path
    server:       str
    user_id:      str
    access_token: str
    device_id:    str


    async def __ainit__(self) -> None:
        self.auth  = Authentication(self)
        self.sync  = Synchronization(self)
        self.rooms = Rooms(self)
        self.e2e   = await Encryption(self, self.e2e_folder)


    @property
    def api(self) -> List[str]:
        return [self.server, "_matrix", "client", "r0"]


    @classmethod
    async def login(
        cls,
        e2e_folder: Union[Path, str],
        server:     str,
        auth:       Dict[str, Any],
    ) -> "Client":

        result = await cls.send_json(
            obj    = cls,
            method = "POST",
            path   = [server, "_matrix", "client", "r0", "login"],
            body   = auth,
        )

        return await cls(
            e2e_folder   = Path(e2e_folder),
            server       = server,
            user_id      = result["user_id"],
            access_token = result["access_token"],
            device_id    = result["device_id"],
        )


    @classmethod
    async def login_password(
        cls,
        e2e_folder:          Union[Path, str],
        server:              str,
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

        return await cls.login(e2e_folder, server, remove_none(auth))


    @classmethod
    async def login_token(
        cls,
        e2e_folder:          Union[Path, str],
        server:              str,
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

        return await cls.login(e2e_folder, server, remove_none(auth))


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
        data   = json.dumps(body).encode()
        result = await cls.send(obj, method, path, parameters, data, headers)
        return json.loads(result)
