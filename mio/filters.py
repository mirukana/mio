# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from dataclasses import dataclass, field
from enum import auto
from typing import TYPE_CHECKING, Dict, List, Optional

from .core.data import JSON, AutoStrEnum, IndexableMap, Parent
from .core.ids import RoomId, UserId
from .module import ClientModule

if TYPE_CHECKING:
    from .client import Client

class EventFormat(AutoStrEnum):
    client     = auto()
    federation = auto()


@dataclass
class EventFilter(JSON):
    limit:       Optional[int]          = None
    types:       Optional[List[str]]    = None
    not_types:   Optional[List[str]]    = None
    senders:     Optional[List[UserId]] = None
    not_senders: Optional[List[UserId]] = None


@dataclass
class RoomEventFilter(EventFilter):
    rooms:                     Optional[List[RoomId]] = None
    not_rooms:                 Optional[List[RoomId]] = None
    lazy_load_members:         bool                   = False
    include_redundant_members: bool                   = False
    contains_url:              Optional[bool]         = None


@dataclass
class RoomFilter(JSON):
    aliases = {"include_left": "include_leave"}

    include_left: bool                   = False
    rooms:        Optional[List[RoomId]] = None
    not_rooms:    Optional[List[RoomId]] = None

    account_data: RoomEventFilter = field(default_factory=RoomEventFilter)
    ephemeral:    RoomEventFilter = field(default_factory=RoomEventFilter)
    timeline:     RoomEventFilter = field(default_factory=RoomEventFilter)
    state:        RoomEventFilter = field(default_factory=RoomEventFilter)


@dataclass
class Filter(JSON):
    event_fields: Optional[List[str]] = None
    event_format: EventFormat         = EventFormat.client
    presence:     EventFilter         = field(default_factory=EventFilter)
    account_data: EventFilter         = field(default_factory=EventFilter)
    room:         RoomFilter          = field(default_factory=RoomFilter)


@dataclass
class FilterStore(ClientModule, IndexableMap[str, Filter]):
    client: Parent["Client"]  = field(repr=False)
    _data:  Dict[str, Filter] = field(default_factory=dict)  # serverID: filter


    async def get_server_id(self, filter: Filter) -> str:
        for server_id, uploaded_filter in self.items():
            if uploaded_filter == filter:
                return server_id

        url   = self.net.api / "user" / self.client.user_id / "filter"
        reply = await self.net.post(url, filter.dict)

        self._data[reply.json["filter_id"]] = filter
        return reply.json["filter_id"]
