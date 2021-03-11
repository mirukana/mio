from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .core.data import JSONFile, Parent

if TYPE_CHECKING:
    from .client import Client


@dataclass
class ClientModule:
    client: Parent["Client"] = field(repr=False)

    @classmethod
    async def load(cls, parent: "Client"):
        return cls(parent)


@dataclass
class JSONClientModule(JSONFile, ClientModule):
    pass
