import shutil
from dataclasses import dataclass, field
from uuid import uuid4

from conftest import new_device_from
from mio.client import Client
from mio.core.types import RoomAlias
from mio.rooms.contents.messages import Emote, Text
from mio.rooms.contents.settings import CanonicalAlias, Name, Topic
from mio.rooms.events import StateEvent, TimelineEvent
from mio.rooms.room import Room
from mio.rooms.rooms import CallbackGroup
from pytest import mark

pytestmark = mark.asyncio


@dataclass
class CallbackGroupTest(CallbackGroup):
    timeline_result:      list = field(default_factory=list)
    state_content_result: list = field(default_factory=list)
    async_state_result:   list = field(default_factory=list)

    def bad_signature(self, room: Room):
        self.timeline_result += ["bad"]

    def on_timeline_event(self, room: Room, event: TimelineEvent):
        self.timeline_result += [room, event.content]

    async def on_state_name_event(self, room: Room, event: StateEvent[Name]):
        self.state_content_result += [room, event.content]

    async def on_state_event(self, room: Room, event: StateEvent):
        self.async_state_result += [room, event.content]


async def test_timeline_event_callback_group(alice: Client, room: Room):
    cb_group = CallbackGroupTest()
    alice.rooms.callback_groups.append(cb_group)

    text  = Text("This is a test")
    emote = Emote("tests")

    await room.timeline.send(text)
    await room.timeline.send(emote)
    # We parse a corresponding timeline event on sync for new states
    await room.state.send(CanonicalAlias())
    await alice.sync.once()

    expected = [room, text, room, emote, room, CanonicalAlias()]
    assert cb_group.timeline_result == expected


async def test_async_and_state_event_callback_group(alice: Client, room: Room):
    cb_group = CallbackGroupTest()
    alice.rooms.callback_groups.append(cb_group)

    topic = Topic("This is not a test")
    name  = Name("Test Room 1000")

    await room.state.send(name)
    await room.state.send(topic)
    await room.timeline.send(CanonicalAlias())
    await alice.sync.once()

    assert cb_group.async_state_result == [room, name, room, topic]


async def test_state_event_content_callback_group(alice: Client, room: Room):
    cb_group = CallbackGroupTest()
    alice.rooms.callback_groups.append(cb_group)

    name = Name("Test Room 1000")

    await room.state.send(name)
    await room.state.send(Topic("Certainly not a test"))
    await room.timeline.send(CanonicalAlias())
    await alice.sync.once()

    assert cb_group.state_content_result == [room, name]


async def test_timeline_event_callback(alice: Client, room: Room):
    got = []
    cb  = lambda r, e: got.extend([r, type(e.content)])  # noqa
    alice.rooms.callbacks[TimelineEvent].append(cb)

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

    alice.rooms.callbacks[Name].append(cb)

    # We will parse a timeline and state version of this event on sync
    await room.state.send(Name("Test room"))
    await alice.sync.once()
    assert got == [room, Name, room, Name]


async def test_state_event_content_callback(alice: Client, room: Room):
    got = []
    cb  = lambda room, event: got.extend([room, type(event.content)])  # noqa
    alice.rooms.callbacks[StateEvent[Name]].append(cb)

    await room.state.send(Name("Test room"))
    await room.state.send(Topic("Not the right content type"))
    await room.timeline.send(CanonicalAlias())
    await alice.sync.once()
    assert got == [room, Name]


async def test_call_callbacks_history(alice: Client, room: Room, tmp_path):
    # Calling callbacks when receiving state and timeline events on syncs

    # The original alice will have already synced due to using the room fixture
    alice2 = await new_device_from(alice, tmp_path)
    tline2 = []
    state2 = []

    alice2.rooms.callbacks[TimelineEvent].append(lambda *a: tline2.append(a))
    alice2.rooms.callbacks[StateEvent].append(lambda *a: state2.append(a))

    await alice2.sync.once()

    # Calling callbacks when loading state and timeline from disk

    alice3 = Client(alice.base_dir)
    tline3 = []
    state3 = []

    alice3.rooms.callbacks[TimelineEvent].append(lambda *a: tline3.append(a))
    alice3.rooms.callbacks[StateEvent].append(lambda *a: state3.append(a))

    await alice3.load()
    await alice3.rooms[room.id].timeline.load_history(9999)
    assert len(tline2) == len(tline3)
    assert len(state2) == len(state3)

    # Calling callbacks when loading timeline from server

    room.state.path.unlink()
    room.timeline.path.unlink()
    for event_dir in room.path.parent.glob("????-??-??"):
        shutil.rmtree(event_dir)

    alice4 = await Client(alice.base_dir).load()
    tline4 = []

    alice4.rooms.callbacks[TimelineEvent].append(lambda *a: tline4.append(a))

    await alice4.rooms[room.id].timeline.load_history(9999)
    assert len(tline2) == len(tline4)


async def test_join_room_id(room: Room, bob: Client):
    await bob.sync.once()
    assert room.id not in bob.rooms

    await bob.rooms.join(room.id, reason="test")
    await bob.sync.once()
    assert room.id in bob.rooms
    assert bob.rooms[room.id].state.me.membership_reason == "test"


async def test_join_room_alias(room: Room, bob: Client):
    assert room.client.user_id != bob.user_id
    alias = RoomAlias(f"#{uuid4()}:localhost")
    await room.create_alias(alias)
    await room.state.send(CanonicalAlias(alias))

    await bob.sync.once()
    assert room.id not in bob.rooms

    await bob.rooms.join(alias, reason="test")
    await bob.sync.once()
    assert room.id in bob.rooms
    assert bob.rooms[room.id].state.me.membership_reason == "test"
