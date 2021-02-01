from dataclasses import dataclass
from typing import TYPE_CHECKING

from . import ClientModule

if TYPE_CHECKING:
    from ..base_client import Client


@dataclass
class Authentication(ClientModule):
    client: "Client"


    async def logout(self) -> None:
        await self.client.send_json("POST", [*self.client.api, "logout"])


    async def logout_all_devices(self) -> None:
        await self.client.send_json(
            "POST", [*self.client.api, "logout", "all"],
        )
