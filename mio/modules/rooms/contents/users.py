from dataclasses import dataclass
from enum import auto
from typing import Optional

from ....core.contents import EventContent
from ....core.data import AutoStrEnum
from ....core.types import MxcUri

# TODO: m.room.third_party_invite


@dataclass
class Member(EventContent):
    class Membership(AutoStrEnum):
        invite = auto()
        join   = auto()
        knock  = auto()
        leave  = auto()
        ban    = auto()

    type    = "m.room.member"
    aliases = {
        "display_name": "displayname",
        "third_party_name": ("third_party_invite", "display_name"),
        # "invite_room_state": ("unsigned", "invite_room_state"),  # TODO
    }

    membership:       Membership
    avatar_url:       Optional[MxcUri] = None
    display_name:     Optional[str]    = None
    is_direct:        bool             = False
    third_party_name: Optional[str]    = None
    # invite_room_state: List[StrippedState] = []  # TODO

    @property
    def left(self) -> bool:
        return self.membership in (self.Membership.leave, self.membership.ban)
