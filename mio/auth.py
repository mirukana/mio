from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict

from yarl import URL

from .core.data import Runtime
from .module import ClientModule

if TYPE_CHECKING:
    from .client import Client


@dataclass
class Auth(ClientModule):
    default_device_name: Runtime[str]  = "mio"
    was_logged_out:      Runtime[bool] = field(default=False, init=False)


    async def login(self, auth: Dict[str, Any]) -> "Client":
        client = self.client

        if self.was_logged_out:
            raise RuntimeError(f"{client} was logged out, create a new client")

        if "device_id" not in auth and client.device_id:
            auth["device_id"] = client.device_id

        if "initial_device_display_name" not in auth:
            auth["initial_device_display_name"]  = self.default_device_name

        reply = await client.send_json("POST", client.api / "login", auth)

        if "well_known" in reply:
            homeserver    = reply["well_known"]["m.homeserver"]
            client.server = URL(homeserver["base_url"])

        client.base_dir     = str(self.client.base_dir).format(**reply)
        client.user_id      = reply["user_id"]
        client.access_token = reply["access_token"]
        client.device_id    = reply["device_id"]

        await client._e2e._upload_keys()
        await client.devices.ensure_tracked([client.user_id])
        await client.save()
        return client


    async def login_password(self, user: str, password: str) -> "Client":
        return await self.login({
            "type":     "m.login.password",
            "user":     user,
            "password": password,
        })


    async def login_token(self, user: str, token: str) -> "Client":
        return await self.login({
            "type":  "m.login.token",
            "user":  user,
            "token": token,
        })


    async def logout(self) -> None:
        await self.client.send_json("POST", self.client.api / "logout")
        self.client.access_token = ""
        self.was_logged_out      = True
        await self.client.save()


    async def logout_all_devices(self) -> None:
        await self.client.send_json("POST", self.client.api / "logout" / "all")
        self.client.access_token = ""
        self.was_logged_out      = True
        await self.client.save()
