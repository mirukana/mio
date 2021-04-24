import shutil
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict

from yarl import URL

from .core.data import Runtime
from .core.files import encode_name
from .core.ids import UserId
from .module import ClientModule

if TYPE_CHECKING:
    from .client import Client


@dataclass
class Auth(ClientModule):
    default_device_name: Runtime[str] = "mio"


    async def login(self, auth: Dict[str, Any]) -> "Client":
        client = self.client

        if client._terminated:
            raise RuntimeError(f"{client} was terminated, create a new client")

        if "device_id" not in auth and client.device_id:
            auth["device_id"] = client.device_id

        if "initial_device_display_name" not in auth:
            auth["initial_device_display_name"]  = self.default_device_name

        reply = await self.net.post(self.net.api / "login", auth)

        if "well_known" in reply.json:
            homeserver    = reply.json["well_known"]["m.homeserver"]
            client.server = URL(homeserver["base_url"])

        unexpanded_base_dir = str(client.base_dir)
        client.base_dir     = unexpanded_base_dir.format(
            user_id   = encode_name(reply.json["user_id"]),
            device_id = encode_name(reply.json["device_id"]),
        )

        shutil.move(unexpanded_base_dir, str(client.base_dir))

        client.user_id      = UserId(reply.json["user_id"])
        client.access_token = reply.json["access_token"]
        client.device_id    = reply.json["device_id"]

        client._acquire_lock()

        await client.e2e._upload_keys()
        await client.devices.ensure_tracked([client.user_id])
        await client.profile._query()
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
        await self.net.post(self.net.api / "logout")
        await self.client.terminate()
        await self.client.save()  # save lack of access_token


    async def logout_all_devices(self) -> None:
        await self.net.post(self.net.api / "logout" / "all")
        await self.client.terminate()
        await self.client.save()  # save lack of access_token
