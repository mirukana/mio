# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from dataclasses import dataclass
from typing import Optional, Set

from ...core.contents import EventContent
from ...core.ids import UserId


@dataclass
class Redaction(EventContent):
    type = "m.room.redaction"

    reason: Optional[str] = None


@dataclass
class Typing(EventContent):
    type    = "m.typing"
    aliases = {"users": "user_ids"}

    users: Set[UserId]
