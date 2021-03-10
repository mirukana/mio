from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ..utils import JSONFile, Parent

if TYPE_CHECKING:
    from ..base_client import Client


@dataclass
class ClientModule:
    client: Parent["Client"] = field(repr=False)

    @classmethod
    async def load(cls, path: Path, parent: "Client"):
        raise NotImplementedError()


@dataclass
class JSONClientModule(JSONFile, ClientModule):
    pass
