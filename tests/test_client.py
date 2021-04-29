# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from pathlib import Path

import filelock
from aiopath import AsyncPath
from conftest import clone_client, compare_clients, read_json
from mio.client import Client
from mio.net.exchange import Request
from pytest import mark, raises
from yarl import URL

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
    alice2 = Client(alice.base_dir)
    assert alice2._lock is None

    with raises(filelock.Timeout):
        # Try creating another client with same base_dir
        await alice2.load(user_id=alice.user_id, device_id=alice.device_id)

    assert alice2._lock and not alice2._lock.is_locked  # type: ignore


async def test_load_from_dir(alice: Client, tmp_path: Path):
    new = clone_client(alice)
    await new.load(user_id=alice.user_id, device_id=alice.device_id)
    compare_clients(new, alice, token=True)


async def test_terminate(alice: Client):
    assert alice._lock
    assert alice._lock.is_locked
    assert not alice.net._session.closed
    assert not alice._terminated

    await alice.terminate()
    assert not alice._lock.is_locked
    assert alice.net._session.closed
    assert alice._terminated

    with raises(RuntimeError):
        await alice.net.send(Request("GET", URL("http://example.com"), None))


async def test_context_manager(alice: Client):
    async with alice as client:
        assert not client._terminated

    assert alice._terminated
