import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

from . import client_modules


@dataclass
class BaseClient:
    homeserver: str


    def __post_init__(self) -> None:
        self.auth  = client_modules.Authentication(self)
        self.sync  = client_modules.Synchronization(self)
        self.rooms = client_modules.Rooms(self)


    @property
    def api(self) -> str:
        return f"{self.homeserver}/_matrix/client/r0"


    async def send(
        self,
        method:     str,
        url:        str,
        parameters: Optional[Dict[str, Any]] = None,
        body:       Optional[Dict[str, Any]] = None,
        headers:    Optional[Dict[str, Any]] = None,
    ) -> bytes:

        raise NotImplementedError()


    async def json_send(self, *send_args, **send_kwargs) -> Dict[str, Any]:
        return json.loads(await self.send(*send_args, **send_kwargs))
