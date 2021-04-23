from pathlib import Path

from aiopath import AsyncPath
from conftest import clone_client, compare_clients, read_json
from filelock import Timeout
from pytest import mark

from mio.client import Client

pytestmark = mark.asyncio


async def test_bare_init(alice: Client, tmp_path: Path):
    client = Client(
        tmp_path,
        alice.server,
        alice.device_id,
        alice.user_id,
        alice.access_token,
    )

    assert client.path == AsyncPath(tmp_path / "client.json")

    assert read_json(client.path) == {
        "server": alice.server,
        "user_id": alice.user_id,
        "access_token": alice.access_token,
        "device_id": alice.device_id,
    }


async def test_file_lock(alice: Client, tmp_path: Path):
    success = True
    alice2  = Client(alice.base_dir)

    assert alice2._lock is None

    try:
        # Try creating another client with same base_dir
        await alice2.load(user_id=alice.user_id, device_id=alice.device_id)
    except Timeout:
        success = False

    assert not alice2._lock.is_locked
    assert not success


async def test_load_from_dir(alice: Client, tmp_path: Path):
    new = clone_client(alice)
    await new.load(user_id=alice.user_id, device_id=alice.device_id)
    compare_clients(new, alice, token=True)
