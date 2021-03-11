from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict

from ...core.data import IndexableMap, Parent
from ...core.types import RoomId
from ..module import ClientModule
from .room import Room

if TYPE_CHECKING:
    from ...client import Client


@dataclass
class Rooms(ClientModule, IndexableMap[RoomId, Room]):
    client: Parent["Client"]   = field(repr=False)
    _data:  Dict[RoomId, Room] = field(default_factory=dict)


    @classmethod
    async def load(cls, parent: "Client") -> "Rooms":
        rooms = cls(parent)

        for room_dir in (parent.path.parent / "rooms").glob("!*"):
            id              = RoomId(room_dir.name)
            rooms._data[id] = await Room.load(parent, id=id)

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
