# mio

Experimental high-level Python Matrix library, with support for end-to-end 
encryption and persistence.

## Installation

Requires Python 3.6 or later and olm 3 development headers.

```sh
pip3 install -U --user .
```

## Development

Install in editable mode and with dev dependencies:

```sh
pip3 install -U --user --editable '.[dev]'
```

To run checks, from the project's root folder:

```sh
mypy mio & flake8 mio
python3 -m pytest
```

Using `python3 -m pytest` instead of `pytest` will ensure that the current
folder is added to import paths.

Tests leave a Synapse server (which has a long startup time) running,
use `synctl stop tests/synapse/homeserver.yaml` to stop it.

Tests will be run in parallel by default, add the `--pdb` flag to the pytest
command to disable this and let debugger calls work normally.

## Examples

```py
import asyncio

from mio.client import Client
from mio.rooms.contents.messages import Text
from mio.rooms.contents.settings import Encryption
from rich import print  # pretty printing, installed as a dependency


def on_text_message(room, event):
    print(f"{room.id}: {event.sender}: {event.content.body}")


async def main():
    # Create a new client that saves its state to /tmp/@alice:matrix.org.mio1:
    client = await Client.login_password(
        base_dir  = "/tmp/{user_id}.{device_id}",
        server    = "https://matrix.org",
        user      = "alice",
        password  = "1234",
    )

    # Do one initial sync with the homeserver and see what rooms we have:
    await client.sync.once()
    print(client.rooms, end="\n\n")

    # Create a room, syncing will register it from details given by the server
    room_id = await client.rooms.create("mio example room")
    await client.sync.once()

    # Register a function that will be called when we receive Text events:
    client.rooms.callbacks[Text].append(on_text_message)

    # Enable encryption in the room and send a text message:
    await client.rooms[room_id].state.send(Encryption())
    await client.rooms[room_id].timeline.send(Text("Hello world"))
    await client.sync.once()

    # Explore our room's state and timeline:
    print(client.rooms[room_id].state, end="\n\n")
    print(client.rooms[room_id].timeline)


asyncio.get_event_loop().run_until_complete(main())
```

A previously created client can be loaded again from disk:

```py
import asyncio

from mio.client import Client
from rich import print


async def main():
    client = await Client.load("/tmp/@alice:matrix.org.mio1")

    # For whatever room was loaded first, load at least 20 messages that we 
    # received previously. If we get to the end of what we saved locally, 
    # we ask the server for more.
    await client.rooms[0].timeline.load_history(20)
    print(client.rooms[0].timeline)


asyncio.get_event_loop().run_until_complete(main())
```
