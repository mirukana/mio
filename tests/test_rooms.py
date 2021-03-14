from pytest import mark

from mio.client import Client
from mio.rooms.contents.messages import Emote, Text
from mio.rooms.contents.settings import CanonicalAlias, Name, Topic
from mio.rooms.events import StateEvent, TimelineEvent
from mio.rooms.room import Room

pytestmark = mark.asyncio


async def test_timeline_event_callback(alice: Client, room: Room):
    got = []
    cb  = lambda r, e: got.extend([r, type(e.content)])  # noqa
    alice.rooms.callbacks[TimelineEvent].add(cb)

    await room.timeline.send(Text("This is a test"))
    await room.timeline.send(Emote("tests"))
    # We parse a corresponding timeline event on sync for new states
    await room.state.send(CanonicalAlias())
    await alice.sync.once()
    assert got == [room, Text, room, Emote, room, CanonicalAlias]


async def test_async_and_content_callback(alice: Client, room: Room):
    got = []

    async def cb(room, event):
        got.extend([room, type(event.content)])

    alice.rooms.callbacks[Name].add(cb)

    # We will parse a timeline and state version of this event on sync
    await room.state.send(Name("Test room"))
    await alice.sync.once()
    assert got == [room, Name, room, Name]


async def test_state_event_content_callback(alice: Client, room: Room):
    got = []
    cb  = lambda room, event: got.extend([room, type(event.content)])  # noqa
    alice.rooms.callbacks[StateEvent[Name]].add(cb)

    await room.state.send(Name("Test room"))
    await room.state.send(Topic("Not the right content type"))
    await room.timeline.send(CanonicalAlias())
    await alice.sync.once()
    assert got == [room, Name]
