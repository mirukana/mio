from pytest import mark

from mio.client import Client
from mio.rooms.contents.messages import Text
from mio.rooms.contents.settings import Encryption, Name
from mio.rooms.room import Room
from mio.rooms.state import StateEvent

pytestmark = mark.asyncio


async def test_text_callback(alice: Client, room: Room):
    got = []

    async def callback(*args):
        got.extend(args)

    alice.rooms.callbacks[Text].add(lambda *args: got.extend(args))
    alice.rooms.callbacks[Text].add(callback)

    await room.timeline.send(Text("This is a test"))
    await alice.sync.once()

    assert all(r == room for r in got[0::2])
    assert all(isinstance(e.content, Text) for e in got[1::2])


async def test_state_event_callback(alice: Client, room: Room):
    got = []

    def extend_got(*args):
        got.extend(args)

    alice.rooms.callbacks[StateEvent].add(extend_got)
    alice.rooms.callbacks[StateEvent[Name]].add(extend_got)

    await room.state.send(Encryption())
    await room.state.send(Name("This is a test name"))
    await alice.sync.once()

    assert all(r == room for r in got[0::2])
    assert all(type(e) == StateEvent for e in got[1::2])
    assert isinstance(got[-1].content, Name)
