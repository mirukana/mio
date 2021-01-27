from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, Optional

from ..utils import remove_none
from . import ClientModule

if TYPE_CHECKING:
    from ..base_client import BaseClient


@dataclass
class Authentication(ClientModule):
    client:       "BaseClient"
    user_id:      Optional[str] = ""
    access_token: Optional[str] = ""
    device_id:    Optional[str] = ""


    @property
    def default_device_name(self) -> str:
        return "mio"


    async def login(self, auth_dict: Dict[str, Any]) -> None:
        if auth_dict.get("device_name") is None:
            auth_dict["device_name"] = self.default_device_name

        result = await self.client.json_send(
            method = "POST",
            url    = f"{self.client.api}/login",
            body   = auth_dict,
        )

        self.user_id      = result["user_id"]
        self.access_token = result["access_token"]
        self.device_id    = result["device_id"]


    async def login_password(
        self,
        user:        str,
        password:    str,
        device_name: Optional[str] = None,
        device_id:   Optional[str] = None,
    ) -> None:

        auth_dict = {
            "type":        "m.login.password",
            "user":        user,
            "password":    password,
            "device_name": device_name,
            "device_id":   device_id,
        }

        await self.login(remove_none(auth_dict))


    async def login_token(
        self,
        user:        str,
        token:       str,
        device_name: Optional[str] = None,
        device_id:   Optional[str] = None,
    ) -> None:

        auth_dict = {
            "type":        "m.login.token",
            "user":        user,
            "token":       token,
            "device_name": device_name,
            "device_id":   device_id,
        }

        await self.login(remove_none(auth_dict))


    async def logout(self, all_devices: bool = False) -> None:
        path = "logout/all" if all_devices else "logout"

        await self.client.json_send(
            method = "POST",
            url    = f"{self.client.api}/{path}",
        )

        self.user_id = self.access_token = self.device_id = None
