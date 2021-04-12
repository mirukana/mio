from conftest import new_device_from
from mio.client import Client
from mio.core.types import NoneType
from mio.devices.events import ToDeviceEvent
from mio.e2e.contents import Dummy, Megolm, Olm
from mio.e2e.errors import (
    MegolmBlockedDeviceInForwardChain, MegolmFromBlockedDevice,
    MegolmFromUntrustedDevice, MegolmUntrustedDeviceInForwardChain,
    NoCipherForUs, OlmExcpectedPrekey, OlmSessionError,
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
        assert len(other._e2e.sent_session_requests) == 1

        other_event = other.rooms[e2e_room.id].timeline[-1]
        assert isinstance(other_event.content, Megolm)

        # Test replying to pending forward request of previously untrusted dev.

        await alice.devices.own[other.device_id].trust()
        await other.sync.once()
        assert not alice.devices.own[other.device_id].pending_session_requests
        assert not other._e2e.sent_session_requests

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
    assert next(iter(alice3._e2e.sent_session_requests.values()))[1] == sent_to

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
    event = await event.decryption.original._decrypted()
    assert isinstance(event.content, Text) and event.decryption
    assert event.decryption.forward_chain == [alice.devices.current]

    assert event.decryption.verification_errors == [
        MegolmFromBlockedDevice(alice.devices.current),
        MegolmBlockedDeviceInForwardChain(alice.devices.current),
    ]

    # [forward chain: alice/untrusted →] alice2/trusted → alice3

    alice3.devices.own[alice.device_id].trusted = None
    event = await event.decryption.original._decrypted()
    assert isinstance(event.content, Text) and event.decryption
    assert event.decryption.forward_chain == [alice.devices.current]

    assert event.decryption.verification_errors == [
        MegolmFromUntrustedDevice(alice.devices.current),
        MegolmUntrustedDeviceInForwardChain(alice.devices.current),
    ]


async def test_olm_recovery(alice: Client, bob: Client):
    sent     = 0
    bob_got  = []
    callback = lambda self, event: bob_got.append(event)  # noqa
    bob.devices.callbacks[ToDeviceEvent].append(callback)
    await bob.sync.once()

    bob_curve = bob.devices.current.curve25519

    async def prepare_dummy(clear_alice_sessions=True):
        target        = bob.devices.current
        olms, no_otks = await alice.devices.encrypt(Dummy(), target)
        assert not no_otks

        # Remove sessions to make sure recovery process is creating a new one
        if clear_alice_sessions:
            alice._e2e.sessions[bob_curve].clear()

        return olms[target]

    async def send_check(olm_for_bob_current, expected_error_type=NoneType):
        await alice.devices.send({bob.devices.current: olm_for_bob_current})
        await bob.sync.once()

        nonlocal sent
        sent += 1

        assert len(bob_got) == sent
        assert isinstance(bob_got[-1].decryption.error, expected_error_type)
        return bob_got[-1]

    # Normal decryptable olm

    await send_check(await prepare_dummy())

    # NoCipherForUs

    olmed = await prepare_dummy()
    alice._e2e.sessions[bob_curve].clear()
    olmed.ciphertext.clear()
    await send_check(olmed, NoCipherForUs)
    # this would fail is recovery didn't create a new session
    await send_check(await prepare_dummy())

    # OlmSessionError for existing session

    await send_check(await prepare_dummy(clear_alice_sessions=False))
    olmed = await prepare_dummy()
    olmed.ciphertext[bob_curve].type = Olm.Cipher.Type.normal
    olmed.ciphertext[bob_curve].body = "invalid base64"
    got = await send_check(olmed, OlmSessionError)
    assert not got.decryption.error.was_new_session
    await send_check(await prepare_dummy())

    # OlmSessionError for new session

    olmed = await prepare_dummy()
    olmed.ciphertext[bob_curve].body = "invalid base64"
    got = await send_check(olmed, OlmSessionError)
    assert got.decryption.error.was_new_session
    await send_check(await prepare_dummy())

    # OlmExcpectedPrekey

    olmed = await prepare_dummy()
    olmed.ciphertext[bob_curve].type = Olm.Cipher.Type.normal
    bob._e2e.sessions.clear()
    await send_check(olmed, OlmExcpectedPrekey)
    await send_check(await prepare_dummy())


async def test_broken_olm_lost_forwarded_session_recovery(
    alice: Client, e2e_room: Room, tmp_path,
):
    await e2e_room.timeline.send(Text("sent before other devices exist"))

    # Receive an undecryptable megolm and send a group session request for it

    alice2 = await new_device_from(alice, tmp_path / "second")
    await alice2.sync.once()
    assert isinstance(alice2.rooms[e2e_room.id].timeline[-1].content, Megolm)

    # Respond to alice2's group session request

    await alice.sync.once()
    await alice.devices.own[alice2.device_id].trust()

    # Fail to decrypt alice's response to our group session request,
    # alice2 will create a new olm session and send a new request

    sync_data = await alice2.sync.once(_handle=False)
    assert sync_data
    sync_data["to_device"]["events"][0]["content"]["ciphertext"].clear()
    await alice2.sync._handle_sync(sync_data)
    assert isinstance(alice2.rooms[e2e_room.id].timeline[-1].content, Megolm)

    # Alice responds to the new requerst, then alice2 should be able to decrypt

    await alice.sync.once()
    await alice2.sync.once()
    assert isinstance(alice2.rooms[e2e_room.id].timeline[-1].content, Text)


async def test_olm_session_reordering(alice: Client, bob: Client):
    # Set up a situation where Alice has 2 olm sessions for Bob

    bobdev  = bob.devices.current
    olms, _ = await alice.devices.encrypt(Dummy(), bobdev)
    await alice.devices.send(olms)  # type: ignore

    alice_sessions = alice._e2e.sessions[bobdev.curve25519]
    oldest_session = alice_sessions[0]
    alice_sessions.clear()

    olms, _ = await alice.devices.encrypt(Dummy(), bobdev)
    await alice.devices.send(olms)  # type: ignore

    alice_sessions.appendleft(oldest_session)
    assert len(alice_sessions) == 2
    assert alice_sessions[0] is oldest_session

    # Now make Bob send an olm message using the oldest session

    await bob.sync.once()

    bob_sessions = bob._e2e.sessions[alice.devices.current.curve25519]
    del bob_sessions[-1]

    olms, _ = await bob.devices.encrypt(Dummy(), alice.devices.current)
    await bob.devices.send(olms)  # type: ignore

    # Verify that the oldest session on Alice's side got moved to last position

    await alice.sync.once()
    assert alice_sessions[0] is not oldest_session
    assert alice_sessions[1] is oldest_session
