import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from urllib.parse import quote

from aiohttp import ClientResponseError, ClientSession

from .auth import Auth
from .core.data import JSONFile, Runtime
from .core.errors import ServerError
from .core.types import HttpUrl, UserId
from .core.utils import get_logger
from .devices.devices import Devices
from .e2e.e2e import E2E
from .module import ClientModule
from .rooms.rooms import Rooms
from .sync import Sync

LOG = get_logger()


@dataclass
class Client(JSONFile):
    base_dir:     Runtime[Union[str, Path]]
    server:       HttpUrl = ""  # type: ignore
    device_id:    str     = ""
    user_id:      UserId  = ""  # type: ignore
    access_token: str     = ""

    auth:    Runtime[Auth]    = field(init=False, repr=False)
    rooms:   Runtime[Rooms]   = field(init=False, repr=False)
    sync:    Runtime[Sync]    = field(init=False, repr=False)
    e2e:     Runtime[E2E]     = field(init=False, repr=False)
    devices: Runtime[Devices] = field(init=False, repr=False)

    _session: Runtime[ClientSession] = field(
        init=False, repr=False, default_factory=ClientSession,
    )


    def __post_init__(self) -> None:
        self.auth    = Auth(self)
        self.rooms   = Rooms(self)
        self.sync    = Sync(self)
        self.e2e     = E2E(self)
        self.devices = Devices(self)
        super().__post_init__()


    @property
    def api(self) -> List[str]:
        return [self.server, "_matrix", "client", "r0"]


    @property
    def path(self) -> Path:
        return Path(self.base_dir) / "client.json"


    async def load(self, **base_dir_placeholders: str) -> "Client":
        self.base_dir = str(self.base_dir).format(**base_dir_placeholders)
        await super().load()

        for attr in self.__dict__.values():
            if isinstance(attr, ClientModule):
                await attr.load()

        return self


    async def send(
        self,
        method:     str,
        path:       List[str],
        parameters: Optional[Dict[str, Any]] = None,
        data:       Optional[bytes]          = None,
        headers:    Optional[Dict[str, Any]] = None,
    ) -> bytes:

        headers    = headers or {}
        parameters = parameters or {}
        url_path   = "/".join(quote(p, safe="") for p in path[1:])

        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"

        for key, value in parameters.items():
            if not isinstance(value, str):
                parameters[key] = json.dumps(
                    value, ensure_ascii=False, separators=(",", ":"),
                )

        response = await self._session.request(
            method  = method,
            url     = f"{path[0]}/{url_path}",
            params  = parameters,
            data    = data,
            headers = headers,
        )

        read = await response.read()

        LOG.debug(
            "%s → %s %r params=%r data=%r\n\n← %r\n",
            self.user_id or "client", method, url_path, parameters, data, read,
        )

        try:
            response.raise_for_status()
        except ClientResponseError as e:
            raise ServerError.from_response(
                reply      = read,
                http_code  = e.status,
                message    = e.message,  # noqa
                method     = method,
                path       = url_path,
                parameters = parameters,
                data       = data,
            )

        return read


    async def send_json(
        self,
        method:     str,
        path:       List[str],
        parameters: Optional[Dict[str, Any]] = None,
        body:       Optional[Dict[str, Any]] = None,
        headers:    Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:

        data   = None if body is None else json.dumps(body).encode()
        result = await self.send(method, path, parameters, data, headers)
        return json.loads(result)
