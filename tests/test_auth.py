from pathlib import Path

from aiohttp import ClientSession
from conftest import clone_client, compare_clients, new_device_from
from pytest import mark, raises

from mio.client import Client

pytestmark = mark.asyncio


async def test_login_password(alice: Client, tmp_path: Path):
    # Clone alice, so FileLock does not raise Timeout
    client = clone_client(alice, alice.server, alice.device_id)
    await client.auth.login_password(alice.user_id.localpart, "test")
    compare_clients(client, alice)


async def test_login_token():
    pass  # TODO: when we have SSO support


async def test_logout(alice: Client):
    await alice.sync.once()
    await alice.auth.logout()
    assert not alice.access_token

    alice.net._session = ClientSession()

    with raises(RuntimeError):
        await alice.sync.once()

    with raises(RuntimeError):
        await alice.auth.login_password(alice.user_id, "test")


async def test_logout_all(alice: Client, tmp_path: Path):
    alice2 = await new_device_from(alice, tmp_path)
    assert len(alice2.devices[alice.user_id]) == 2

    await alice.auth.logout_all_devices()
    assert not alice.access_token

    with raises(RuntimeError):
        await alice.sync.once()

    with raises(RuntimeError):
        await alice.auth.login_password(alice.user_id, "test")
