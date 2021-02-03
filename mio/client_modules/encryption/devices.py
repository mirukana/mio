from typing import List, Optional

from pydantic import BaseModel

from ...typing import UserId


class Device(BaseModel):
    user_id:        UserId
    device_id:      str
    ed25519:        str
    curve25519:     str
    e2e_algorithms: List[str]
    display_name:   Optional[str] = None

    def __eq__(self, other) -> bool:
        if not isinstance(other, Device):
            raise TypeError(f"Can't compare Device with {other}")

        return (self.user_id, self.device_id) == \
               (other.user_id, other.device_id)

    def __hash__(self) -> int:
        return hash((self.user_id, self.device_id, self.ed25519))
