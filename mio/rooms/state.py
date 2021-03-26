from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple, Type, Union

from ..core.contents import EventContent
from ..core.data import JSONFile, Map, Parent
from ..core.types import MXC, EventId, RoomAlias, UserId
from .contents.settings import (
    Avatar, CanonicalAlias, Creation, Encryption, GuestAccess,
    HistoryVisibility, JoinRules, Name, PinnedEvents, PowerLevels, ServerACL,
    Tombstone, Topic,
)
from .contents.users import Member
from .events import InvitedRoomStateEvent, StateBase, StateEvent

if TYPE_CHECKING:
    from .room import Room

Key = Union[
    Type[EventContent], str, Tuple[Type[EventContent], str], Tuple[str, str],
]


@dataclass
class RoomState(JSONFile, Map):
    loaders = {
        **JSONFile.loaders,  # type: ignore

        StateBase: lambda v, parent: (  # type: ignore
            StateEvent if "event_id" in v else InvitedRoomStateEvent
        ).from_dict(v, parent),
    }

    room: Parent["Room"] = field(repr=False)

    # {event.type: {event.state_key: event}}
    _data: Dict[Tuple[str, str], StateBase] = field(default_factory=dict)


    def __getitem__(self, key: Key) -> StateBase:
        if not isinstance(key, tuple):
            key = (key, "")  # type: ignore

        if isinstance(key[0], type):  # type: ignore
            key = (key[0].type, key[1])  # type: ignore

        return self._data[key]  # type: ignore


    async def load(self) -> "RoomState":
        await super().load()
        await self._register(*list(self.values()))
        return self


    @property
    def path(self) -> Path:
        return self.room.client.path.parent / "state.json"


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
    def invitees(self) -> Dict[UserId, StateBase[Member]]:
        return self.users(joined=False, left=False, banned=False)


    @property
    def members(self) -> Dict[UserId, StateBase[Member]]:
        return self.users(invitees=False, left=False, banned=False)


    @property
    def leavers(self) -> Dict[UserId, StateBase[Member]]:
        return self.users(invitees=False, joined=False, banned=False)


    @property
    def banned(self) -> Dict[UserId, StateBase[Member]]:
        return self.users(invitees=False, joined=False, left=False)


    @property
    def us(self) -> Optional[StateBase[Member]]:
        return self.users().get(self.room.client.user_id)


    @property
    def inviter(self) -> Optional[UserId]:
        invited = self.us and self.us.content.membership == Member.Kind.invite
        return self.us.sender if self.us and invited else None


    def users(
        self,
        invitees: bool = True,
        joined:   bool = True,
        left:     bool = True,
        banned:   bool = True,
    ) -> Dict[UserId, StateBase[Member]]:

        include = {
            Member.Kind.invite: invitees,
            Member.Kind.join: joined,
            Member.Kind.leave: left,
            Member.Kind.ban: banned,
        }

        return {
            UserId(state_key): event
            for (_mtype, state_key), event in self.items()
            if isinstance(event.content, Member) and
            include[event.content.membership]
        }


    async def send(self, content: EventContent, state_key: str = "") -> str:
        assert content.type
        room = self.room
        url  = room.client.api / "rooms" / room.id / "state" / content.type

        if state_key:
            url = url / state_key

        result = await room.client.send_json("PUT", url, content.dict)
        return result["event_id"]


    async def _register(self, *events: StateBase) -> None:
        for event in events:
            assert event.type
            self._data[event.type, event.state_key] = event
            await self.room._call_callbacks(event)

        await self.save()
