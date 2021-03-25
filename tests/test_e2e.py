from conftest import new_device_from
from mio.client import Client
from mio.e2e.contents import Megolm
from mio.e2e.errors import (
    MegolmBlockedDeviceInForwardChain, MegolmFromBlockedDevice,
    MegolmFromUntrustedDevice, MegolmUntrustedDeviceInForwardChain,
)
from mio.rooms.contents.messages import Text
from mio.rooms.room import Room
from pytest import mark, raises

pytestmark = mark.asyncio

# TODO forward_chain_verif


async def test_session_forwarding(alice: Client, e2e_room: Room, tmp_path):
    # https://github.com/matrix-org/synapse/pull/8675 cross-user sharing broken

    await e2e_room.timeline.send(Text("sent before other devices exist"))

    untrusted = await new_device_from(alice, tmp_path / "unstrusted")
    blocked   = await new_device_from(alice, tmp_path / "blocked")

    for other in (untrusted, blocked):
        await other.sync.once()
        await other.rooms[e2e_room.id].timeline.load_history(1)

    await alice.sync.once()
    await alice.devices.own[blocked.device_id].block()
    assert alice.devices.own[untrusted.device_id].trusted is None
    assert alice.devices.own[blocked.device_id].trusted is False

    for other in (untrusted, blocked):
        # Ensure session requests from untrusted or blocked device are pended

        assert alice.devices.own[other.device_id].pending_session_requests
        assert len(other.e2e.sent_session_requests) == 1

        other_event = other.rooms[e2e_room.id].timeline[-1]
        assert isinstance(other_event.content, Megolm)

        # Test replying to pending forward request of previously untrusted dev.

        await alice.devices.own[other.device_id].trust()
        await other.sync.once()
        assert not alice.devices.own[other.device_id].pending_session_requests
        assert not other.e2e.sent_session_requests

        other_event = other.rooms[e2e_room.id].timeline[-1]
        assert isinstance(other_event.content, Text)


async def test_session_forwarding_already_trusted_device(
    alice: Client, e2e_room: Room, tmp_path,
):
    await e2e_room.timeline.send(Text("sent before other devices exist"))

    alice2 = await new_device_from(alice, tmp_path / "unstrusted")
    await alice.sync.once()
    await alice.devices.own[alice2.device_id].trust()

    await alice2.sync.once()
    await alice2.rooms[e2e_room.id].timeline.load_history(1)
    await alice.sync.once()   # get session request
    await alice2.sync.once()  # get forwarded session

    event = alice2.rooms[e2e_room.id].timeline[-1]
    assert isinstance(event.content, Text)


async def test_cancel_session_forward(alice: Client, e2e_room: Room, tmp_path):
    await e2e_room.timeline.send(Text("sent before other devices exist"))

    alice2 = await new_device_from(alice, tmp_path / "alice2")
    alice3 = await new_device_from(alice, tmp_path / "alice3")

    # Make alice3 send a request to both alice and alice2

    for other in (alice2, alice3):
        await other.sync.once()
        await other.rooms[e2e_room.id].timeline.load_history(1)

    sent_to = {alice.user_id, alice2.user_id}
    assert next(iter(alice3.e2e.sent_session_requests.values()))[1] == sent_to

    # Make alice respond to alice3's request before alice2

    await alice.sync.once()
    await alice.devices.own[alice3.device_id].trust()
    await alice3.sync.once()

    # alice3 got alice's response, so it should have cancelled alice2's request

    cancelled = False
    sync_data = await alice2.sync.once()
    assert sync_data

    for event in sync_data["to_device"]["events"]:
        if event["content"]["action"] == "request_cancellation":
            cancelled = True

    assert cancelled


async def test_forwarding_chains(alice: Client, e2e_room: Room, tmp_path):
    await e2e_room.timeline.send(Text("sent before other devices exist"))

    # [no forward chain] alice/trusted → alice2

    alice2 = await new_device_from(alice, tmp_path / "alice2")

    await alice.sync.once()
    await alice.devices.own[alice2.device_id].trust()
    await alice2.devices.own[alice.device_id].trust()

    await alice2.sync.once()
    await alice2.rooms[e2e_room.id].timeline.load_history(1)
    await alice.sync.once()   # get session request
    await alice2.sync.once()  # get forwarded session

    event = alice2.rooms[e2e_room.id].timeline[-1]
    assert isinstance(event.content, Text) and event.decryption
    assert not event.decryption.forward_chain
    assert not event.decryption.verification_errors

    # [forward chain: alice/trusted →] alice2/trusted → alice3

    alice3 = await new_device_from(alice, tmp_path / "alice3")

    await alice2.sync.once()
    await alice2.devices.own[alice3.device_id].trust()
    await alice3.devices.own[alice.device_id].trust()
    await alice3.devices.own[alice2.device_id].trust()

    await alice3.sync.once()
    await alice3.rooms[e2e_room.id].timeline.load_history(1)
    await alice2.sync.once()  # get session request
    await alice3.sync.once()  # get forwarded session

    event = alice3.rooms[e2e_room.id].timeline[-1]
    assert isinstance(event.content, Text) and event.decryption
    assert event.decryption.forward_chain == [alice.devices.current]
    assert not event.decryption.verification_errors

    # [forward chain: alice/blocked →] alice2/trusted → alice3

    await alice3.devices.own[alice.device_id].block()
    event = await event.decryption.original.decrypted()
    assert isinstance(event.content, Text) and event.decryption
    assert event.decryption.forward_chain == [alice.devices.current]

    assert event.decryption.verification_errors == [
        MegolmFromBlockedDevice(alice.devices.current),
        MegolmBlockedDeviceInForwardChain(alice.devices.current),
    ]

    # [forward chain: alice/untrusted →] alice2/trusted → alice3

    alice3.devices.own[alice.device_id].trusted = None
    event = await event.decryption.original.decrypted()
    assert isinstance(event.content, Text) and event.decryption
    assert event.decryption.forward_chain == [alice.devices.current]

    assert event.decryption.verification_errors == [
        MegolmFromUntrustedDevice(alice.devices.current),
        MegolmUntrustedDeviceInForwardChain(alice.devices.current),
    ]
