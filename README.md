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
```

## Examples

```py
import asyncio

from mio.client import Client
from mio.rooms.contents.messages import Text
from mio.rooms.contents.settings import Encryption
from rich import print  # pretty printing, installed as a dependency


async def main():
    # Create a new client that saves its state to /tmp/@alice:matrix.org.mio1:
    client = await Client.login_password(
        base_dir  = "/tmp/{user_id}.{device_id}",
        server    = "https://matrix.org",
        user      = "alice",
        password  = "1234",
        device_id = "mio1",
    )

    # Do one initial sync with the server:
    await client.sync.once()

    # See what rooms we have available, explore a room's state and timeline:
    print(client.rooms)
    print(client.rooms["!ex:ample.org"].state)
    print(client.rooms["!ex:ample.org"].timeline)

    # Enable encryption in said room, then send a text message:
    await client.rooms["!ex:ample.org"].state.send(Encryption())
    await client.rooms["!ex:ample.org"].timeline.send(Text("Hello world"))


asyncio.get_event_loop().run_until_complete(main())
```

A previously created client can be loaded again from disk:

```py
import asyncio

from mio.client import Client
from rich import print


async def main():
    client = await Client.load("/tmp/@alice:matrix.org.mio1")

    # Load at least 20 messages that we received previously in this room.
    # If we get to the end of what we saved locally, ask the server for more:
    await client.rooms["!ex:ample.org"].timeline.load_history(20)
    print(client.rooms["!ex:ample.org"].timeline)


asyncio.get_event_loop().run_until_complete(main())
```
