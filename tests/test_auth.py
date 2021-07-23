# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

import asyncio
from pathlib import Path

from aiohttp import ClientSession
from pytest import mark, raises

from mio.client import Client
from mio.net.errors import MatrixError

from .conftest import clone_client, compare_clients, new_device_from

pytestmark = mark.asyncio


async def test_login_password(alice: Client, tmp_path: Path):
    # Clone alice, so FileLock does not raise Timeout
    client = clone_client(alice, alice.server, alice.device_id)
    await client.auth.login_password(alice.user_id.localpart, "test")
    compare_clients(client, alice)


async def test_sso(synapse, tmp_path):
    client = Client(tmp_path, synapse.url)
    server = client.auth.start_sso_server()

    async def send():
        while not server._runner.addresses:
            await asyncio.sleep(0.1)

        with raises(MatrixError):  # "SSO requires a valid public_baseurl"
            await client.net.get(server.login_url)

        url = server.login_url % {"loginToken": "abc"}
        await client.net.get(url)

    # stupid hack, asyncio.ensure_future doesn't work in pytest
    await asyncio.gather(server._start(), send())

    with raises(MatrixError):  # invalid token
        await client.auth.login_token(await server)


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
