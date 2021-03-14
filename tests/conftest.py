import json
from pathlib import Path
from typing import Union
from uuid import uuid4

from mio.client import Client
from pytest import fixture
from synapse import SynapseHandle


def pytest_addoption(parser):
    parser.addoption(
        "-S",
        "--keep-servers",
        action = "store_true",
        help   = (
            "Keep Synapse running after tests end to reduce the startup time "
            "of next tests"
        ),
    )


async def get_client(synapse: SynapseHandle, path: Path, name: str) -> Client:
    name = f"{name}.{uuid4()}"
    path = path / "{user_id}.{device_id}"
    synapse.register(name)
    return await Client.login_password(path, synapse.url, name, "test")


def read_json(path: Union[Path, str]) -> dict:
    return json.loads(Path(path).read_text())


@fixture(scope="session")
def synapse(request):
    server = SynapseHandle()
    server.start()
    yield server

    if not request.config.getoption("--keep-servers"):
        server.destroy()


@fixture
async def alice(synapse, tmp_path):
    client = await get_client(synapse, tmp_path, "alice")
    yield client
    await client._session.close()  # TODO: public method for this


@fixture
async def bob(synapse, tmp_path):
    client = await get_client(synapse, tmp_path, "bob")
    yield client
    await client._session.close()

@fixture
async def room(alice):
    room_id = await alice.rooms.create("Room")
    await alice.sync.once()
    return alice.rooms[room_id]
