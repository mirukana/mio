# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..core.contents import ContentT
from ..core.data import Parent
from ..core.events import Event
from ..core.logging import MioLogger

if TYPE_CHECKING:
    from ..client import Client


@dataclass
class AccountDataEvent(Event[ContentT]):
    client:     Parent["Client"] = field(repr=False)
    content:    ContentT

    @property
    def logger(self) -> MioLogger:
        return self.client
