from pathlib import Path
from uuid import uuid4

from conftest import read_json
from mio.client import Client
from pytest import mark, raises

pytestmark = mark.asyncio


def compare_clients(client1: Client, client2: Client, token: bool = False):
    assert client1.base_dir == client2.base_dir
    assert client1.server == client2.server
    assert client1.user_id == client2.user_id
    assert client1.device_id == client2.device_id

    if token:
        assert client1.access_token == client2.access_token


async def test_bare_init(alice: Client, tmp_path: Path):
    client = await Client(
        tmp_path,
        alice.server,
        alice.user_id,
        alice.access_token,
        alice.device_id,
    )

    assert client.path == tmp_path / "client.json"
    assert not client.rooms._data
    assert not client.sync.next_batch
    assert client.e2e.account

    assert read_json(client.path) == {
        "server": alice.server,
        "user_id": alice.user_id,
        "access_token": alice.access_token,
        "device_id": alice.device_id,
    }


async def test_load_from_dir(alice: Client):
    with raises(FileNotFoundError):
        await Client.load(f"/random/{uuid4()}")

    compare_clients(await Client.load(alice.base_dir), alice, token=True)


async def test_login_password(alice: Client):
    username = alice.user_id.split(":")[0][1:]
    client = await Client.login_password(
        alice.base_dir, alice.server, username, "test", alice.device_id, "m",
    )
    compare_clients(client, alice)


async def test_login_token():
    pass  # TODO: when we have SSO support
