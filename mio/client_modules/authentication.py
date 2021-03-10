from dataclasses import dataclass

from ..utils import Frozen
from .client_module import ClientModule


@dataclass
class Authentication(ClientModule, Frozen):
    async def logout(self) -> None:
        await self.client.send_json("POST", [*self.client.api, "logout"])


    async def logout_all_devices(self) -> None:
        await self.client.send_json(
            "POST", [*self.client.api, "logout", "all"],
        )
