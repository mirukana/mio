import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

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
    def api(self) -> List[str]:
        return ["_matrix", "client", "r0"]


    async def send(
        self,
        method:     str,
        path:       List[str],
        parameters: Optional[Dict[str, Any]] = None,
        data:       Optional[bytes]          = None,
        headers:    Optional[Dict[str, Any]] = None,
    ) -> bytes:

        raise NotImplementedError()


    async def send_json(
        self,
        method:     str,
        path:       List[str],
        parameters: Optional[Dict[str, Any]] = None,
        body:       Optional[Dict[str, Any]] = None,
        headers:    Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:

        data   = json.dumps(body).encode()
        result = await self.send(method, path, parameters, data, headers)
        return json.loads(result)
