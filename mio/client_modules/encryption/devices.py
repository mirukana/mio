from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Device:
    user_id:              str
    device_id:            str
    ed25519:              str
    curve25519:           str
    supported_algorithms: List[str]
    display_name:         Optional[str] = None
