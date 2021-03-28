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
mypy mio & flake8 mio & python3 -m pytest
```

Using `python3 -m pytest` instead of `pytest` will ensure that the current
folder is added to import paths.

Arguments that can be added to the pytest command include:

- Paths to the files in *tests/* to run, instead of running everything
- `--pdb` to disable parallel testing and let debugger calls work normally
- `--capture=no`/`-s` to show logging output and prints in real time
- `--cov` to generate test coverage info, terminal and HTML by default

Tests leave a Synapse server (which has a long startup time) running,
use `synctl stop tests/synapse/homeserver.yaml` to stop it.
The server's log is available at *tests/synapse/homeserver.log*.


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
    client = Client(base_dir="/tmp/mio-example", server="https://example.org")

    # Register a function that will be called when we receive Text events:
    client.rooms.callbacks[Text].append(on_text_message)

    if client.path.exists():
        await client.load()
    else:
        await client.auth.login_password("alice", "1234")

    # Sync with the server to update the client's state:
    await client.sync.once()

    # Create a room and sync to make it available in client.rooms:
    room_id = await client.rooms.create("mio example room")
    await client.sync.once()

    # Enable encryption in the room and send a text message:
    await client.rooms[room_id].state.send(Encryption())
    await client.rooms[room_id].timeline.send(Text("Hello world"))
    await client.sync.once()

    # Explore our room's state and timeline:
    print(client.rooms[room_id].state, end="\n\n")
    print(client.rooms[room_id].timeline)


asyncio.get_event_loop().run_until_complete(main())
```
