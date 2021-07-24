# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from pytest import mark, raises

from mio.client import Client
from mio.core.ids import EventId
from mio.net.errors import MatrixError
from mio.rooms.contents.messages import Text
from mio.rooms.contents.settings import Creation
from mio.rooms.events import SendStep, TimelineEvent
from mio.rooms.room import Room

pytestmark = mark.asyncio


async def test_load_event(room: Room):
    new = []
    cb  = lambda room, event: new.append((room, event))  # noqa
    room.client.rooms.callbacks[TimelineEvent].append(cb)

    event_id = room.timeline[0].id
    got      = await room.timeline.load_event(event_id)
    assert isinstance(got.content, Creation)
    assert not new

    del room.timeline._data[event_id]
    got = await room.timeline.load_event(event_id)
    assert isinstance(got.content, Creation)
    assert len(new) == 1


async def test_send_to_lazy_encrypted_room(e2e_room: Room, bob: Client):
    await e2e_room.invite(bob.user_id)
    await bob.rooms.join(e2e_room.id)
    await e2e_room.client.sync.once()

    assert not e2e_room.state.all_users_loaded
    await e2e_room.timeline.send(Text("hi"))
    assert e2e_room.state.all_users_loaded
    assert len(e2e_room.state.users) == 2

    await bob.sync.once()
    assert isinstance(bob.rooms[e2e_room.id].timeline[-1].content, Text)


async def test_local_echo(e2e_room: Room):
    new = []
    cb  = lambda room, event: new.append(event)  # noqa
    e2e_room.client.rooms.callbacks[Text].append(cb)

    initial_events = len(e2e_room.timeline)
    await e2e_room.timeline.send(Text("hi"), transaction_id="abc")
    assert len(e2e_room.timeline) == initial_events + 1

    for event in new:
        assert event.content == Text("hi")
        assert event.sender == e2e_room.client.user_id
        assert not event.decryption

    assert new[0].id == "$echo.abc"
    assert new[0].sending == SendStep.sending
    assert new[0].id not in e2e_room.timeline

    assert new[1].id != new[0].id
    assert new[1].sending == SendStep.sent
    assert new[1].id in e2e_room.timeline

    await e2e_room.client.sync.once()
    assert new[2].sending == SendStep.synced
    assert len(new) == 3
    assert len(e2e_room.timeline) == initial_events + 1


async def test_multiclient_local_echo(e2e_room: Room, bob: Client):
    new1 = []
    cb1  = lambda room, event: new1.append(event)  # noqa
    e2e_room.client.rooms.callbacks[Text].append(cb1)

    new2 = []
    cb2  = lambda room, event: new2.append(event)  # noqa
    bob.rooms.callbacks[Text].append(cb2)

    await bob.rooms.join(e2e_room.id)
    await bob.sync.once()

    await e2e_room.timeline.send(Text("hi"), [e2e_room.client, bob])
    assert new1 == new2


async def test_sending_failure(room: Room, bob: Client):
    new = []
    cb  = lambda room, event: new.append((event.id, event.sending))  # noqa
    room.client.rooms.callbacks[TimelineEvent].append(cb)

    await room.timeline.send(Text("abc"))
    await bob.rooms.join(room.id)  # prevent room from becoming inaccessible
    await room.leave()

    # Event that has failed sending in timeline

    with raises(MatrixError):
        await room.timeline.send(Text("def"), transaction_id="123")

    unsent_id = EventId("$echo.123")
    assert new[-1] == (unsent_id, SendStep.failed)
    assert unsent_id in room.timeline
    assert list(room.timeline.unsent) == [unsent_id]
    assert room.timeline.unsent[unsent_id].content == Text("def")
    assert room.timeline.unsent[unsent_id].sending == SendStep.failed
    assert not room.timeline.unsent[unsent_id].historic

    # Failed in unsent but not timeline._data after client restart

    await room.client.terminate()
    client2 = Client(room.client.base_dir)
    new     = []
    cb      = lambda room, event: new.append((event.id, event.sending))  # noqa
    client2.rooms.callbacks[TimelineEvent].append(cb)

    await client2.load()
    assert new == [(unsent_id, SendStep.failed)]

    timeline2 = client2.rooms[room.id].timeline
    assert unsent_id in timeline2
    assert list(timeline2.unsent) == [unsent_id]
    assert timeline2.unsent[unsent_id].content == Text("def")
    assert timeline2.unsent[unsent_id].sending == SendStep.failed
    assert timeline2.unsent[unsent_id].historic

    # Retry sending that failed

    await client2.rooms.join(room.id)
    event_id = await timeline2.resend_failed(timeline2.unsent[unsent_id])
    assert timeline2[event_id].sending == SendStep.sent
    assert not timeline2.unsent
    assert new[-1] == (event_id, SendStep.sent)

    with raises(AssertionError):
        await timeline2.resend_failed(timeline2[event_id])
