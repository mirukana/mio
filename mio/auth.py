from dataclasses import dataclass

from .module import ClientModule


@dataclass
class Auth(ClientModule):
    async def logout(self) -> None:
        await self.client.send_json("POST", [*self.client.api, "logout"])


    async def logout_all_devices(self) -> None:
        await self.client.send_json(
            "POST", [*self.client.api, "logout", "all"],
        )