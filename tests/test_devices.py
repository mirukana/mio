from pathlib import Path

from mio.client import Client
from mio.core.errors import MatrixError
from mio.rooms.contents.messages import Text
from mio.rooms.room import Room
from pytest import mark, raises

pytestmark = mark.asyncio


async def test_tracking(alice: Client, e2e_room: Room, bob: Client, tmp_path):
    await bob.rooms.join(e2e_room.id)
    await bob.sync.once()
    await bob.rooms[e2e_room.id].timeline.send(Text("makes alice get my key"))

    assert bob.user_id not in alice.devices
    await alice.sync.once()
    bob_dev1 = bob.devices.current
    assert alice.devices[bob.user_id] == {bob_dev1.device_id: bob_dev1}

    args     = (tmp_path, bob.server, bob.user_id, "test")
    bob2     = await Client.login_password(*args)
    bob_dev2 = bob2.devices.current

    await alice.sync.once()
    await bob.sync.once()
    await e2e_room.timeline.send(Text("notice bob's new device"))
    await bob.rooms[e2e_room.id].timeline.send(Text("notice my new device"))

    assert alice.devices[bob.user_id] == bob.devices.own == {
        bob_dev1.device_id: bob_dev1,
        bob_dev2.device_id: bob_dev2,
    }

    await bob2.sync.once()
    assert isinstance(bob2.rooms[e2e_room.id].timeline[-1].content, Text)

    # TODO: left
