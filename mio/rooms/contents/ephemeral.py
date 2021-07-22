# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from dataclasses import dataclass
from datetime import datetime
from typing import NamedTuple, Optional, Set

from ...core.contents import EventContent
from ...core.data import JSON
from ...core.ids import EventId, UserId
from ...core.utils import DictS


@dataclass
class Typing(EventContent):
    type    = "m.typing"
    aliases = {"users": "user_ids"}

    users: Set[UserId]


@dataclass
class Receipts(EventContent):
    class Entry(NamedTuple):
        type:   str
        event:  EventId
        sender: UserId
        date:   Optional[datetime] = None

    type = "m.receipt"

    source: DictS

    @classmethod
    def from_dict(
        cls, data: DictS, parent: Optional[JSON] = None,
    ) -> "Receipts":
        return cls(source=data)
