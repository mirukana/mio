from mio.client import Client
from mio.rooms.contents.settings import Creation
from mio.rooms.contents.users import Member
from mio.rooms.room import Room
from pytest import mark, raises

pytestmark = mark.asyncio


async def test_indexing(room: Room):
    creation = room.state._data["m.room.create", ""]
    assert isinstance(creation.content, Creation)

    assert room.state["m.room.create"] == creation
    assert room.state["m.room.create", ""] == creation
    assert room.state[Creation] == creation
    assert room.state[Creation, ""] == creation

    us = room.state._data["m.room.member", room.client.user_id]
    assert isinstance(us.content, Member)
    assert us.state_key == room.client.user_id

    assert room.state["m.room.member", room.client.user_id] == us
    assert room.state[Member, room.client.user_id] == us

    with raises(KeyError):
        room.state["m.room.member"]

    with raises(KeyError):
        room.state[Member]
