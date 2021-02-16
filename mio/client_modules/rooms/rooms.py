from typing import TYPE_CHECKING, Dict

from pydantic import PrivateAttr

from ...typing import RoomId
from ...utils import MapModel
from .. import ClientModule
from .room import Room

if TYPE_CHECKING:
    from ...base_client import Client


class Rooms(ClientModule, MapModel):
    _data: Dict[RoomId, Room] = PrivateAttr(default_factory=dict)


    @classmethod
    async def load(cls, client: "Client") -> "Rooms":
        rooms = cls(client=client)

        for room_dir in (client.save_dir / "rooms").glob("!*"):
            room = await Room.load(client=client, id=RoomId(room_dir.name))
            rooms._data[room.id] = room

        return rooms


    @property
    def invited(self) -> Dict[RoomId, Room]:
        return {k: v for k, v in self.items() if v.invited and not v.left}


    @property
    def joined(self) -> Dict[RoomId, Room]:
        return {k: v for k, v in self.items() if not v.invited and not v.left}


    @property
    def left(self) -> Dict[RoomId, Room]:
        return {k: v for k, v in self.items() if v.left}
