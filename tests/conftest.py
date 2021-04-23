import json
from pathlib import Path
from shutil import copytree
from typing import Union
from uuid import uuid4

from pytest import fixture
from synapse import SynapseHandle

from mio.client import Client
from mio.rooms.contents.settings import Encryption


def pytest_configure(config):
    SynapseHandle()


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


async def get_client(synapse: SynapseHandle, path: Path, name: str) -> Client:
    name = f"{name}.{uuid4()}"
    path = path / "{user_id}.{device_id}"
    synapse.register(name)
    return await Client(path, synapse.url).auth.login_password(name, "test")


async def new_device_from(client: Client, path: Path) -> Client:
    new = Client(path, client.server)
    return await new.auth.login_password(client.user_id, "test")


def read_json(path: Union[Path, str]) -> dict:
    return json.loads(Path(path).read_text())


@fixture
def synapse():
    return SynapseHandle()


@fixture
async def alice(synapse, tmp_path):
    client = await get_client(synapse, tmp_path, "alice")
    yield client
    await client.net.disconnect()


@fixture
async def bob(synapse, tmp_path):
    client = await get_client(synapse, tmp_path, "bob")
    yield client
    await client.net.disconnect()


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
