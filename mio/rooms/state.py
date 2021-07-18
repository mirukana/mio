# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from collections import ChainMap
from dataclasses import dataclass, field
from itertools import islice
from typing import (
    TYPE_CHECKING, DefaultDict, Dict, List, NamedTuple, Optional, Set, Tuple,
    Union,
)

from aiopath import AsyncPath

from ..core.contents import EventContent, EventContentType, str_type
from ..core.data import JSONFile, Map, Parent, Runtime
from ..core.events import InvalidEvent
from ..core.ids import MXC, EventId, RoomAlias, UserId
from ..core.utils import comma_and_join, remove_none
from .contents.settings import (
    Avatar, CanonicalAlias, Creation, Encryption, GuestAccess,
    HistoryVisibility, JoinRules, Name, PinnedEvents, ServerACL, Tombstone,
    Topic,
)
from .contents.users import PowerLevels
from .events import InvitedRoomStateEvent, StateBase, StateEvent
from .user import RoomUser

if TYPE_CHECKING:
    from .room import Room

_Key = Union[EventContentType, Tuple[EventContentType, str]]


@dataclass
class RoomState(JSONFile, Map):
    loaders = {
        **JSONFile.loaders,  # type: ignore

        StateBase: lambda v, parent: (  # type: ignore
            StateEvent if "event_id" in v else InvitedRoomStateEvent
        ).from_dict(v, parent),
    }

    room: Parent["Room"] = field(repr=False)

    # {(event.type, event.state_key): event}
    _data: Dict[Tuple[str, str], StateBase] = field(default_factory=dict)

    invitees: Runtime[Dict[UserId, RoomUser]] = field(default_factory=dict)
    members:  Runtime[Dict[UserId, RoomUser]] = field(default_factory=dict)
    leavers:  Runtime[Dict[UserId, RoomUser]] = field(default_factory=dict)
    banned:   Runtime[Dict[UserId, RoomUser]] = field(default_factory=dict)

    _all_users_queried: bool = False

    # {name: {user_id}} - For detecting multiple users having a same name
    _display_names: Runtime[Dict[str, Set[UserId]]] = field(
        init=False, repr=False, default_factory=lambda: DefaultDict(set),
    )


    def __getitem__(self, key: _Key) -> StateBase:
        if not isinstance(key, tuple):
            key = (key, "")
        return self._data[str_type(key[0]), key[1]]


    async def load(self) -> "RoomState":
        await super().load()

        for event in self.values():
            event.from_disk = True

        await self._register(*list(self.values()))
        return self


    @property
    def path(self) -> AsyncPath:
        return self.room.path.parent / "state.json"


    @property
    def creator(self) -> UserId:
        return self[Creation].sender


    @property
    def federated(self) -> bool:
        return self[Creation].content.federate


    @property
    def version(self) -> str:
        return self[Creation].content.version


    @property
    def predecessor(self) -> Optional[Creation.Predecessor]:
        return self[Creation].content.predecessor


    @property
    def encryption(self) -> Optional[Encryption]:
        return self[Encryption].content if Encryption in self else None


    @property
    def display_name(self) -> str:
        return self.name or self.alias or str(self.user_based_name)


    @property
    def user_based_name(self) -> "UserBasedRoomName":
        names    = tuple(user.unique_name for user in self.heroes.values())
        joined   = self.total_members
        invited  = self.total_invitees

        return UserBasedRoomName(
            empty  = joined + invited <= 1,
            names  = names,
            others = max(0, joined + invited - 1 - len(names)),  # - 1 = us
        )


    @property
    def name(self) -> Optional[str]:
        return self[Name].content.name if Name in self else None


    @property
    def topic(self) -> Optional[str]:
        return self[Topic].content.topic if Topic in self else None


    @property
    def avatar(self) -> Optional[MXC]:
        return self[Avatar].content.url if Avatar in self else None


    @property
    def alias(self) -> Optional[RoomAlias]:
        got = CanonicalAlias in self
        return self[CanonicalAlias].content.alias if got else None


    @property
    def alt_aliases(self) -> List[RoomAlias]:
        got = CanonicalAlias in self
        return self[CanonicalAlias].content.alternatives if got else []


    @property
    def join_rule(self) -> JoinRules.Rule:
        return self[JoinRules].content.rule


    @property
    def history_visibility(self) -> HistoryVisibility.Visibility:
        if HistoryVisibility in self:
            return self[HistoryVisibility].content.visibility
        return HistoryVisibility.Visibility.shared


    @property
    def guest_access(self) -> GuestAccess.Access:
        d = GuestAccess.Access.forbidden
        return self[GuestAccess].content.access if GuestAccess in self else d


    @property
    def pinned_events(self) -> List[EventId]:
        got = PinnedEvents in self
        return self[PinnedEvents].content.pinned if got else []


    @property
    def tombstone(self) -> Optional[Tombstone]:
        return self[Tombstone].content if Tombstone in self else None


    @property
    def power_levels(self) -> PowerLevels:
        missing = PowerLevels(state_default=0)
        return self[PowerLevels].content if PowerLevels in self else missing


    @property
    def server_acl(self) -> ServerACL:
        default = ServerACL(allow=["*"])
        return self[ServerACL].content if ServerACL in self else default


    @property
    def total_members(self) -> int:
        if self.all_users_loaded:
            return len(self.members)
        return self.room._lazy_load_joined or 0


    @property
    def total_invitees(self) -> int:
        if self.all_users_loaded:
            return len(self.invitees)
        return self.room._lazy_load_invited or 0


    @property
    def heroes(self) -> Dict[UserId, RoomUser]:
        if not self.all_users_loaded and self.room._lazy_load_heroes:
            return {u: self.users[u] for u in self.room._lazy_load_heroes}

        def get(*dicts: Dict[UserId, RoomUser]) -> Dict[UserId, RoomUser]:
            our_id = self.room.client.user_id
            users  = ChainMap(*dicts).items()
            return dict(islice(
                ((uid, user) for uid, user in users if uid != our_id), 5,
            ))

        main = get(self.invitees, self.members)
        return main or get(self.leavers) or get(self.banned)


    @property
    def users(self) -> ChainMap[UserId, RoomUser]:
        # The ChainMap iterates from last to first child dict
        return ChainMap(self.banned, self.leavers, self.invitees, self.members)


    @property
    def me(self) -> RoomUser:
        return self.users[self.room.client.user_id]


    @property
    def all_users_loaded(self) -> bool:
        if self.room.invited or self.room.left:
            return False

        lazy = self.room._lazy_load_joined is not None
        return not lazy or self._all_users_queried


    async def load_all_users(self) -> bool:
        if self.all_users_loaded:
            return False

        room   = self.room
        url    = room.net.api / "rooms" / room.id / "members"
        params = {"at": room.client.sync.next_batch}
        reply  = await room.net.get(url % remove_none(params))

        state_evs: List[StateEvent] = []

        for source in reply.json.get("chunk", []):
            with room.client.report(InvalidEvent):
                state_evs.append(StateEvent.from_dict(source, room))

        await self._register(*state_evs)

        if not room.invited and not room.left:
            self._all_users_queried = True

        return True


    async def send(
        self, content: EventContent, state_key: str = "",
    ) -> EventId:

        assert content.type
        room = self.room
        url  = room.net.api / "rooms" / room.id / "state" / content.type

        if state_key:
            url = url / state_key

        reply = await room.net.put(url, content.dict)
        return EventId(reply.json["event_id"])


    async def _register(self, *events: StateBase) -> None:
        for event in events:
            assert event.type
            self._data[event.type, event.state_key] = event
            await self.room._call_callbacks(event)

        await self.save()


class UserBasedRoomName(NamedTuple):
    empty:  bool
    names:  Tuple[str, ...]
    others: int

    def __str__(self) -> str:
        if self.others:
            who = comma_and_join(*self.names, f"{self.others} more")
        else:
            who = comma_and_join(*self.names)

        if self.empty and who:
            return f"Empty Room (had {who})"
        if self.empty:
            return "Empty Room"
        return who
