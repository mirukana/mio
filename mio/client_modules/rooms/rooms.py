from typing import Dict

from pydantic import PrivateAttr

from ...typing import RoomId
from ...utils import MapModel
from .. import ClientModule
from . import Room


class Rooms(ClientModule, MapModel):
    _data: Dict[RoomId, Room] = PrivateAttr(default_factory=dict)


    @property
    def invited(self) -> Dict[RoomId, Room]:
        return {k: v for k, v in self.items() if v.invited and not v.left}


    @property
    def joined(self) -> Dict[RoomId, Room]:
        return {k: v for k, v in self.items() if not v.invited and not v.left}


    @property
    def left(self) -> Dict[RoomId, Room]:
        return {k: v for k, v in self.items() if v.left}
