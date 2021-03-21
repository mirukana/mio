from pathlib import Path

from conftest import new_device_from
from mio.client import Client
from mio.core.errors import MatrixError
from mio.rooms.contents.messages import Text
from mio.rooms.room import Room
from pytest import mark, raises

pytestmark = mark.asyncio


async def test_tracking(alice: Client, e2e_room: Room, bob: Client, tmp_path):
    # Get initial devices of users we share an encrypted room with:

    await bob.rooms.join(e2e_room.id)
    await bob.sync.once()
    await bob.rooms[e2e_room.id].timeline.send(Text("makes alice get my key"))

    bob_dev1 = bob.devices.current
    assert bob.user_id not in alice.devices
    assert bob_dev1.curve25519 not in alice.devices.by_curve

    await alice.sync.once()
    assert alice.devices[bob.user_id] == {bob_dev1.device_id: bob_dev1}
    assert alice.devices.by_curve[bob_dev1.curve25519] == bob_dev1

    # Notice a user's new devices at runtime and share session with it:

    bob2     = await new_device_from(bob, tmp_path)
    bob_dev2 = bob2.devices.current

    await alice.sync.once()
    await bob.sync.once()
    await e2e_room.timeline.send(Text("notice bob's new device"))
    await bob.rooms[e2e_room.id].timeline.send(Text("notice my new device"))

    assert alice.devices[bob.user_id] == bob.devices.own == {
        bob_dev1.device_id: bob_dev1,
        bob_dev2.device_id: bob_dev2,
    }
    assert alice.devices.by_curve[bob_dev1.curve25519] == bob_dev1
    assert alice.devices.by_curve[bob_dev2.curve25519] == bob_dev2

    await bob2.sync.once()
    assert isinstance(bob2.rooms[e2e_room.id].timeline[-1].content, Text)

    # Stop tracking devices of users we no longer share an encrypted room with:

    await bob.rooms[e2e_room.id].leave()
    await alice.sync.once()
    assert bob.user_id not in alice.devices
    assert bob_dev1.curve25519 not in alice.devices.by_curve
    assert bob_dev2.curve25519 not in alice.devices.by_curve


async def test_discard_gone_user_devices(alice: Client, tmp_path):
    await alice.sync.once()
    dev1 = alice.devices.current
    assert list(alice.devices.own.values()) == [dev1]

    alice2 = await new_device_from(alice, tmp_path)
    dev2   = alice2.devices.current
    await alice.sync.once()
    assert list(alice.devices.own.values()) == [dev1, dev2]

    await alice2.auth.logout()
    await alice.sync.once()
    assert list(alice.devices.own.values()) == [dev1]
