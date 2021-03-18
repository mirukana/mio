from mio.client import Client
from mio.e2e.contents import Megolm
from mio.e2e.errors import (
    MegolmPayloadFromBlockedDevice, MegolmPayloadFromUntrustedDevice,
)
from mio.rooms.contents.messages import Text
from mio.rooms.room import Room
from pytest import mark, raises

pytestmark = mark.asyncio


async def test_trust(alice: Client, e2e_room: Room, bob: Client):
    bob_dev = bob.devices.current
    await bob.rooms.join(e2e_room.id)
    await bob.sync.once()
    await bob.rooms[e2e_room.id].timeline.send(Text("makes alice get my key"))
    await alice.sync.once()

    assert alice.devices[bob.user_id][bob_dev.device_id].trusted is None
    await e2e_room.timeline.send(Text("unset"))
    await bob.sync.once()
    assert isinstance(bob.rooms[e2e_room.id].timeline[-1].content, Text)

    await alice.devices[bob.user_id][bob_dev.device_id].trust()
    assert alice.devices[bob.user_id][bob_dev.device_id].trusted is True
    await e2e_room.timeline.send(Text("trusted"))
    await bob.sync.once()
    assert isinstance(bob.rooms[e2e_room.id].timeline[-1].content, Text)

    await alice.devices[bob.user_id][bob_dev.device_id].block()
    assert alice.devices[bob.user_id][bob_dev.device_id].trusted is False
    await e2e_room.timeline.send(Text("blocked"))
    await bob.sync.once()
    assert isinstance(bob.rooms[e2e_room.id].timeline[-1].content, Megolm)


async def test_trust_megolm_validation(alice: Client, e2e_room, bob: Client):
    bob_dev = bob.devices.current
    await bob.rooms.join(e2e_room.id)
    await bob.sync.once()
    await bob.rooms[e2e_room.id].timeline.send(Text("makes alice get my key"))
    await alice.sync.once()

    assert alice.devices[bob.user_id][bob_dev.device_id].trusted is None
    await bob.rooms[e2e_room.id].timeline.send(Text("unset"))
    await alice.sync.once()
    error = e2e_room.timeline[-1].decryption.verification_error
    assert isinstance(error, MegolmPayloadFromUntrustedDevice)

    await alice.devices[bob.user_id][bob_dev.device_id].trust()
    await bob.rooms[e2e_room.id].timeline.send(Text("trusted"))
    await alice.sync.once()
    assert not e2e_room.timeline[-1].decryption.verification_error

    await alice.devices[bob.user_id][bob_dev.device_id].block()
    await bob.rooms[e2e_room.id].timeline.send(Text("blocked"))
    await alice.sync.once()
    error = e2e_room.timeline[-1].decryption.verification_error
    assert isinstance(error, MegolmPayloadFromBlockedDevice)
    assert error.device is alice.devices[bob.user_id][bob_dev.device_id]
