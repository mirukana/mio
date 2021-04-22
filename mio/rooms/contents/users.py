from dataclasses import dataclass
from enum import auto
from typing import Optional

from ...core.contents import EventContent
from ...core.data import AutoStrEnum
from ...core.ids import MXC

# TODO: m.room.third_party_invite


@dataclass
class Member(EventContent):
    class Kind(AutoStrEnum):
        invite = auto()
        join   = auto()
        leave  = auto()
        ban    = auto()

    type    = "m.room.member"
    aliases = {
        "display_name": "displayname",
        "third_party_name": ("third_party_invite", "display_name"),
        # "invite_room_state": ("unsigned", "invite_room_state"),  # TODO
    }

    membership:       Kind
    reason:           Optional[str] = None
    display_name:     Optional[str] = None
    avatar_url:       Optional[MXC] = None
    is_direct:        bool          = False
    third_party_name: Optional[str] = None
    # invite_room_state: List[StrippedState] = []  # TODO

    @property
    def absent(self) -> bool:
        return self.membership in (self.Kind.leave, self.Kind.ban)
