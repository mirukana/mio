from dataclasses import dataclass, field
from typing import Dict

from .. import ClientModule
from . import InvitedRoom, JoinedRoom, LeftRoom, Room


@dataclass
class Rooms(ClientModule):
    invited: Dict[str, InvitedRoom] = field(default_factory=dict)
    joined:  Dict[str, JoinedRoom]  = field(default_factory=dict)
    left:    Dict[str, LeftRoom]    = field(default_factory=dict)

    @property
    def all(self) -> Dict[str, Room]:
        return {**self.joined, **self.invited, **self.left}
