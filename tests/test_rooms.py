from dataclasses import dataclass, field
from uuid import uuid4

from pytest import mark

from mio.client import Client
from mio.core.types import RoomAlias
from mio.rooms.callbacks import CallbackGroup
from mio.rooms.contents.messages import Emote, Text
from mio.rooms.contents.settings import CanonicalAlias, Name, Topic
from mio.rooms.events import StateEvent, TimelineEvent
from mio.rooms.room import Room

pytestmark = mark.asyncio


@dataclass
class CallbackGroupTest(CallbackGroup):
    timeline_result:       list = field(default_factory=list)
    # text_test_pass: bool = False
    # text_test_pass: bool = False

    async def async_timeline(self, room: Room, event: TimelineEvent):
        self.timeline_result += [room, type(event.content)]

    def timeline_name_does_not_matter(self, room: Room, event: TimelineEvent):
        self.timeline_result += [room, type(event.content)]


async def test_callback_group(alice: Client, room: Room):
    cb_group = CallbackGroupTest()
    alice.rooms.callback_groups.append(cb_group)

    await room.timeline.send(Text("This is a test"))
    await room.timeline.send(Emote("tests"))
    # We parse a corresponding timeline event on sync for new states
    await room.state.send(CanonicalAlias())
    await alice.sync.once()

    result = [
        room, Text,           room, Text,
        room, Emote,          room, Emote,
        room, CanonicalAlias, room, CanonicalAlias,
    ]

    assert cb_group.timeline_result == result


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


async def test_join_room_id(room: Room, bob: Client):
    await bob.sync.once()
    assert room.id not in bob.rooms

    await bob.rooms.join(room.id)
    await bob.sync.once()
    assert room.id in bob.rooms


async def test_join_room_alias(room: Room, bob: Client):
    assert room.client.user_id != bob.user_id
    alias = RoomAlias(f"#{uuid4()}:localhost")
    await room.create_alias(alias)
    await room.state.send(CanonicalAlias(alias))

    await bob.sync.once()
    assert room.id not in bob.rooms

    await bob.rooms.join(alias)
    await bob.sync.once()
    assert room.id in bob.rooms
