from uuid import uuid4

from mio.core.types import RoomAlias
from mio.rooms.contents.settings import CanonicalAlias
from mio.rooms.room import Room
from pytest import mark

pytestmark = mark.asyncio


async def test_create_alias(room: Room):
    alias = RoomAlias(f"#{uuid4()}:localhost")
    await room.create_alias(alias)
    await room.state.send(CanonicalAlias(alias))
    await room.client.sync.once()
    assert room.state[CanonicalAlias.type][""].content.alias == alias
