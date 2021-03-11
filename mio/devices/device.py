from dataclasses import dataclass, field
from typing import List, Optional

from ..core.types import UserId


@dataclass(unsafe_hash=True)
class Device:
    user_id:        UserId
    device_id:      str
    ed25519:        str           = field(compare=False)
    curve25519:     str           = field(compare=False)
    e2e_algorithms: List[str]     = field(compare=False)
    display_name:   Optional[str] = field(default=None, compare=False)
