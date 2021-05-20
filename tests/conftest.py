# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from shutil import copytree
from typing import Union
from uuid import uuid4

from aioresponses import aioresponses
from diff_cover.diff_cover_tool import main  # type: ignore
from pytest import fixture

from mio.client import Client
from mio.rooms.contents.settings import Encryption

from .synapse import SynapseHandle


class TestData:
    def __getattr__(self, name: str) -> Path:
        name = re.sub(r"(.*)_", r"\1.", name).replace("_", "-")
        return Path(f"tests/data/{name}")


@dataclass
class ClientFactory:
    path:    Path
    synapse: SynapseHandle

    async def __getattr__(self, name: str) -> Client:
        name = f"{name}.{uuid4()}"
        path = self.path / "{user_id}.{device_id}"
        self.synapse.register(name)
        client = Client(path, self.synapse.url)
        return await client.auth.login_password(name, "test")


def pytest_configure(config):
    SynapseHandle()


def pytest_unconfigure(config):
    if config.option.cov_source:
        print()

        cov_dir = Path(__file__).parent / "coverage"
        xml     = str(cov_dir / "output.xml")
        html    = str(cov_dir / "diff.html")
        exit    = main(["", xml, "--html-report", html, "--fail-under", "100"])

        print(f"\nHTML diff coverage showing missing lines written to {html}")

        if exit != 0:
            sys.exit(exit)


def compare_clients(client1: Client, client2: Client, token: bool = False):
    assert client1.server == client2.server
    assert client1.user_id == client2.user_id
    assert client1.device_id == client2.device_id

    if token:
        assert client1.access_token == client2.access_token


def clone_client(client: Client, *args, **kwargs) -> Client:
    dest_dir     = Path(client.base_dir).parent / str(uuid4())
    new_base_dir = dest_dir / Path(client.base_dir).name
    dest_dir.mkdir()

    copytree(client.base_dir, new_base_dir)

    return Client(new_base_dir, *args, **kwargs)


async def new_device_from(client: Client, path: Path) -> Client:
    new = Client(path, client.server)
    return await new.auth.login_password(client.user_id, "test")


def read_json(path: Union[Path, str]) -> dict:
    return json.loads(Path(path).read_text())


@fixture
def data():
    return TestData()


@fixture
def mock_responses():
    with aioresponses() as mock:
        yield mock


@fixture
def synapse():
    return SynapseHandle()


@fixture
def clients(tmp_path, synapse):
    return ClientFactory(tmp_path, synapse)


@fixture
async def alice(synapse, tmp_path):
    client = await ClientFactory(tmp_path, synapse).alice
    yield client
    await client.terminate()


@fixture
async def bob(synapse, tmp_path):
    client = await ClientFactory(tmp_path, synapse).bob
    yield client
    await client.terminate()


@fixture
async def room(alice):
    room_id = await alice.rooms.create(public=True)
    await alice.sync.once()
    return alice.rooms[room_id]


@fixture
async def room2(alice):
    room_id = await alice.rooms.create(public=True)
    await alice.sync.once()
    return alice.rooms[room_id]


@fixture
async def e2e_room(room):
    await room.state.send(Encryption())
    await room.client.sync.once()
    return room
