from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..base_client import Client


@dataclass
class ClientModule:
    client: "Client"
