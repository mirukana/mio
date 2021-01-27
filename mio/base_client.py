import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .client_modules.authentication import Authentication
from .client_modules.encryption.encryption import Encryption
from .client_modules.rooms import Rooms
from .client_modules.synchronizer import Synchronization


@dataclass
class BaseClient:
    homeserver: str

    def __post_init__(self) -> None:
        self.auth  = Authentication(client=self)
        self.sync  = Synchronization(client=self)
        self.rooms = Rooms(client=self)
        self.e2e   = Encryption(client=self)


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
