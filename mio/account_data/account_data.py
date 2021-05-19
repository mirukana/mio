# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, DefaultDict, Dict, List

from aiopath import AsyncPath

from ..core.callbacks import CallbackGroup, Callbacks, EventCallbacks
from ..core.contents import EventContent, EventContentType, str_type
from ..core.data import Map, Parent, Runtime
from ..module import JSONClientModule
from .events import AccountDataEvent

if TYPE_CHECKING:
    from ..client import Client

_Map = Map[str, AccountDataEvent]


@dataclass
class AccountData(JSONClientModule, _Map, EventCallbacks):
    client: Parent["Client"] = field(repr=False)

    # {event.type: event}
    _data: Dict[str, AccountDataEvent] = field(default_factory=dict)

    callbacks: Runtime[Callbacks] = field(
        init=False, repr=False, default_factory=lambda: DefaultDict(list),
    )

    callback_groups: Runtime[List[CallbackGroup]] = field(
        init=False, repr=False, default_factory=list,
    )


    def __getitem__(self, key: EventContentType) -> AccountDataEvent:
        return self._data[str_type(key)]


    @property
    def path(self) -> AsyncPath:
        return self.client.path.parent / "account_data.json"


    async def send(self, content: EventContent) -> None:
        assert content.type
        uid = self.client.user_id
        url = self.net.api / "user" / uid / "account_data" / content.type
        await self.net.put(url, content.dict)


    async def _register(self, *events: AccountDataEvent) -> None:
        for event in events:
            assert event.type
            self._data[event.type] = event
            await self._call_callbacks(event)

        await self.save()
