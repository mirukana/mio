from conftest import read_json
from mio.client import Client
from pytest import mark

pytestmark = mark.asyncio


async def test_client_bare_init(alice, tmp_path):
    client = await Client(
        tmp_path,
        alice.server,
        alice.user_id,
        alice.access_token,
        alice.device_id,
    )

    assert not client.rooms._data
    assert not client.sync.next_batch
    assert client.e2e.account

    assert read_json(tmp_path / "client.json") == {
        "server": alice.server,
        "user_id": alice.user_id,
        "access_token": alice.access_token,
        "device_id": alice.device_id,
    }
