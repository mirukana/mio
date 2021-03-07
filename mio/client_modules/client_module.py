from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Type

from ..utils import JSONFile, Runtime

if TYPE_CHECKING:
    from ..base_client import Client


@dataclass
class ClientModule:
    client: Runtime["Client"] = field(repr=False)

    @classmethod
    async def load(cls, path: Path, **defaults):
        raise NotImplementedError()


@dataclass
class JSONClientModule(JSONFile, ClientModule):
    @classmethod
    def forward_references(cls) -> Dict[str, Type]:
        from ..base_client import Client
        return {"Client": Client}
