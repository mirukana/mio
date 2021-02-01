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
        if auth_dict.get("initial_device_display_name") is None:
            auth_dict["initial_device_display_name"] = self.default_device_name

        result = await self.client.send_json(
            method = "POST",
            path   = [*self.client.api, "login"],
            body   = auth_dict,
        )

        self.user_id      = result["user_id"]
        self.access_token = result["access_token"]
        self.device_id    = result["device_id"]


    async def login_password(
        self,
        user:        str,
        password:    str,
        device_id:   Optional[str] = None,
        device_name: Optional[str] = None,
    ) -> None:

        auth_dict = {
            "type":                        "m.login.password",
            "user":                        user,
            "password":                    password,
            "device_id":                   device_id,
            "initial_device_display_name": device_name,
        }

        await self.login(remove_none(auth_dict))


    async def login_token(
        self,
        user:        str,
        token:       str,
        device_id:   Optional[str] = None,
        device_name: Optional[str] = None,
    ) -> None:

        auth_dict = {
            "type":                        "m.login.token",
            "user":                        user,
            "token":                       token,
            "device_id":                   device_id,
            "initial_device_display_name": device_name,
        }

        await self.login(remove_none(auth_dict))


    async def logout(self, all_devices: bool = False) -> None:
        path = "logout/all" if all_devices else "logout"

        await self.client.send_json(
            method = "POST",
            path   = [*self.client.api, path],
        )

        self.user_id = self.access_token = self.device_id = None
