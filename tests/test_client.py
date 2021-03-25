from pathlib import Path

from conftest import compare_clients, read_json
from mio.client import Client
from pytest import mark, raises

pytestmark = mark.asyncio


async def test_bare_init(alice: Client, tmp_path: Path):
    client = Client(
        tmp_path,
        alice.server,
        alice.device_id,
        alice.user_id,
        alice.access_token,
    )

    assert client.path == tmp_path / "client.json"

    assert read_json(client.path) == {
        "server": alice.server,
        "user_id": alice.user_id,
        "access_token": alice.access_token,
        "device_id": alice.device_id,
    }


async def test_load_from_dir(alice: Client):
    new = Client(alice.base_dir)
    await new.load(user_id=alice.user_id, device_id=alice.device_id)
    assert new.path == alice.path
    compare_clients(new, alice, token=True)
