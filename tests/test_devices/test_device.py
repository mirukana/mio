# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from pytest import mark, raises

from mio.client import Client
from mio.e2e.contents import Megolm
from mio.e2e.errors import MegolmFromBlockedDevice, MegolmFromUntrustedDevice
from mio.net.errors import MatrixError
from mio.rooms.contents.messages import Text
from mio.rooms.room import Room

from ..conftest import new_device_from

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
    error = e2e_room.timeline[-1].decryption.verification_errors[0]
    assert isinstance(error, MegolmFromUntrustedDevice)

    await alice.devices[bob.user_id][bob_dev.device_id].trust()
    await bob.rooms[e2e_room.id].timeline.send(Text("trusted"))
    await alice.sync.once()
    assert not e2e_room.timeline[-1].decryption.verification_errors

    await alice.devices[bob.user_id][bob_dev.device_id].block()
    await bob.rooms[e2e_room.id].timeline.send(Text("blocked"))
    await alice.sync.once()
    error = e2e_room.timeline[-1].decryption.verification_errors[0]
    assert isinstance(error, MegolmFromBlockedDevice)
    assert error.device is alice.devices[bob.user_id][bob_dev.device_id]


async def test_delete(alice: Client, tmp_path):
    alice2 = await new_device_from(alice, tmp_path)
    await alice.devices.update([alice.user_id])
    await alice.devices.own[alice2.device_id].delete_password("test")
    assert alice2.device_id not in alice.devices.own

    with raises(MatrixError):
        await alice2.sync.once()

    await alice.devices.current.delete({
        "type":     "m.login.password",
        "user":     alice.user_id,
        "password": "test",
    })
    assert alice.device_id not in alice.devices.own
    assert not alice.access_token
    assert alice._terminated
