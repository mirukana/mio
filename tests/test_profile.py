from conftest import new_device_from
from mio.client import Client
from mio.core.types import MXC
from pytest import mark

pytestmark = mark.asyncio


async def test_changes(alice: Client, bob: Client, room, room2):
    await alice.sync.once()
    # We'll make sure the callback is only called once when multiple member
    # events (due to multiple rooms) come for the same change
    assert len(alice.rooms) == 2
    assert alice.profile.name != "Alice Margatroid"
    assert alice.profile.avatar != "mxc://localhost/1"

    # Make sure too we don't query profile due to events not concerning us
    assert room.id not in bob.rooms
    await bob.rooms.join(room.id)

    calls = []
    alice.profile.callback = lambda self: calls.append(self)

    await alice.profile.set_name("Alice Margatroid")
    await alice.profile.set_avatar(MXC("mxc://localhost/1"))
    await alice.sync.once()

    assert calls == [alice.profile]
    assert alice.profile.name == "Alice Margatroid"
    assert alice.profile.avatar == MXC("mxc://localhost/1")


async def test_changes_no_room_joined(alice: Client):
    assert not alice.rooms
    assert not alice.sync.next_batch  # not synced

    await alice.profile.set_name("Alice Margatroid")
    await alice.profile.set_avatar(MXC("mxc://localhost/1"))

    await alice.sync.once()
    assert alice.profile.name == "Alice Margatroid"
    assert alice.profile.avatar == MXC("mxc://localhost/1")


async def test_query_on_login(alice: Client, tmp_path):
    await alice.profile.set_name("Alice Margarine")
    await alice.profile.set_avatar(MXC("mxc://localhost/1"))

    alice2 = await new_device_from(alice, tmp_path)
    assert not alice2.sync.next_batch  # not synced
    assert alice2.profile.name == "Alice Margarine"
    assert alice2.profile.avatar == MXC("mxc://localhost/1")
