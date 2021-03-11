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
from mio.client import Client
from mio.rooms.contents.messages import Text
from mio.rooms.contents.settings import Encryption
from devtools import debug

# Create a new client that saves its state to */tmp/@alice:matrix.org.mio1*:
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
debug(client.rooms)
debug(client.rooms["!ex:ample.org"].state)
debug(client.rooms["!ex:ample.org"].timeline)

# Enable encryption in said room, then send a text message:
await client.rooms["!ex:ample.org"].state.send(Encryption())
await client.rooms["!ex:ample.org"].timeline.send(Text("Hello world"))
```

A previously created client can be loaded again from disk:

```py
from mio.client import Client
client = await Client.load("/tmp/@alice:matrix.org.mio1")

# Load at least 20 messages that we received previously in this room.
# If we get to the end of what we saved locally, ask the server for more:
await client.rooms["!ex:ample.org"].timeline.load_history(20)
debug(client.rooms["!ex:ample.org"].timeline)
```
