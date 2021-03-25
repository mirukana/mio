from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Union

from .core.data import JSONFile, Parent

if TYPE_CHECKING:
    from .client import Client


@dataclass
class ClientModule:
    client: Parent["Client"] = field(repr=False)

    async def load(self) -> Union["ClientModule", "JSONFile"]:
        pass


@dataclass
class JSONClientModule(JSONFile, ClientModule):
    pass
