from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..base_client import BaseClient


@dataclass
class ClientModule:
    client: "BaseClient"
