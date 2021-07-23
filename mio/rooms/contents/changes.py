# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from dataclasses import dataclass
from typing import Optional

from ...core.contents import EventContent
from ...core.utils import DictS


@dataclass
class Redaction(EventContent):
    type = "m.room.redaction"

    reason: Optional[str] = None


@dataclass
class Redacted(EventContent):
    @classmethod
    def matches(cls, event: DictS) -> bool:
        content = event.get("content", {})
        return "redacted_because" in event.get("unsigned", {}) and not content
