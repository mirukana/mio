from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Dict

from ...typing import RoomId
from ...utils import Frozen, Map
from ..client_module import ClientModule
from .room import Room

if TYPE_CHECKING:
    from ...base_client import Client


@dataclass
class Rooms(ClientModule, Frozen, Map[RoomId, Room]):
    path:   Path               = field(repr=False)
    client: "Client"           = field(repr=False)
    _data:  Dict[RoomId, Room] = field(default_factory=dict)


    @classmethod
    async def load(cls, path: Path, **defaults) -> "ClientModule":
        defaults["path"] = path
        rooms            = cls(**defaults)

        for room_dir in path.glob("!*"):
            id = RoomId(room_dir.name)

            rooms._data[id] = await Room.load(
                path   = rooms.room_path(id),
                client = defaults["client"],
                id     = id,
            )

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


    def room_path(self, room_id: str) -> Path:
        return self.path / room_id / "room.json"
