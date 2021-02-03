from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, Union

from pydantic import AnyHttpUrl, Field

from .typing import UserId
from .utils import AsyncInit, FileModel, remove_none


class Client(FileModel, AsyncInit):
    save_dir:     Path
    server:       AnyHttpUrl
    user_id:      UserId
    access_token: str
    device_id:    str

    e2e:   Encryption      = Field(None)
    rooms: Rooms           = Field(None)
    auth:  Authentication  = Field(None)
    sync:  Synchronization = Field(None)

    __repr_exclude__ = ("e2e", "rooms", "auth", "sync")
    __json__         = {
        "include": {"server", "user_id", "access_token", "device_id"},
    }


    async def __ainit__(self) -> None:
        self.e2e   = await Encryption.load(self)
        self.rooms = await Rooms.load(self)
        self.auth  = Authentication(client=self)
        self.sync  = Synchronization(client=self)
        await self._save()


    @property
    def api(self) -> List[str]:
        return [self.server, "_matrix", "client", "r0"]


    @property
    def save_file(self) -> Path:
        return self.save_dir / "client.json"


    @classmethod
    async def load(cls, save_dir: Union[Path, str]) -> "Client":
        data = await cls._read_json(Path(save_dir) / "client.json")
        return await cls(save_dir=Path(save_dir), **data)


    @classmethod
    async def login(
        cls,
        save_dir: Union[Path, str],
        server:   AnyHttpUrl,
        auth:     Dict[str, Any],
    ) -> "Client":
        """Login to a homeserver using a custom authentication dict.

        The `save_dir`, folder where client data will be stored, can contain
        `{user_id}` and `{device_id}` placeholders that will be
        automatically filled.
        """

        result = await cls.send_json(
            obj    = cls,
            method = "POST",
            path   = [server, "_matrix", "client", "r0", "login"],
            body   = auth,
        )

        save_dir = str(save_dir).format(
            user_id=result["user_id"], device_id=result["device_id"],
        )

        return await cls(
            save_dir     = Path(save_dir),
            server       = server,
            user_id      = result["user_id"],
            access_token = result["access_token"],
            device_id    = result["device_id"],
        )


    @classmethod
    async def login_password(
        cls,
        save_dir:            Union[Path, str],
        server:              AnyHttpUrl,
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

        return await cls.login(save_dir, server, remove_none(auth))


    @classmethod
    async def login_token(
        cls,
        save_dir:            Union[Path, str],
        server:              AnyHttpUrl,
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

        return await cls.login(save_dir, server, remove_none(auth))


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


# Required to avoid circular import

from .client_modules.authentication import Authentication
from .client_modules.encryption.encryption import Encryption
from .client_modules.rooms import Rooms
from .client_modules.synchronizer import Synchronization

Client.update_forward_refs()
