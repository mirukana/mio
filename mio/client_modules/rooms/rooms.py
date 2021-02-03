from typing import Dict

from ...typing import RoomId
from .. import ClientModule
from . import InvitedRoom, JoinedRoom, LeftRoom, Room


class Rooms(ClientModule):
    invited: Dict[RoomId, InvitedRoom] = {}
    joined:  Dict[RoomId, JoinedRoom]  = {}
    left:    Dict[RoomId, LeftRoom]    = {}

    @property
    def all(self) -> Dict[RoomId, Room]:
        return {**self.joined, **self.invited, **self.left}
