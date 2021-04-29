# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Union

from .core.data import JSONFile, Parent

if TYPE_CHECKING:
    from .client import Client
    from .net.net import Network


@dataclass
class ClientModule:
    client: Parent["Client"] = field(repr=False)


    @property
    def net(self) -> "Network":
        return self.client.net


    async def load(self) -> Union["ClientModule", "JSONFile"]:
        pass


@dataclass
class JSONClientModule(JSONFile, ClientModule):
    pass
