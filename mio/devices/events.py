# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from ..core.contents import ContentT
from ..core.data import Parent, Runtime
from ..core.events import Event
from ..core.ids import UserId
from ..core.logging import MioLogger
from ..core.utils import DictS
from ..e2e.contents import Olm
from ..e2e.errors import OlmDecryptionError, OlmVerificationError

if TYPE_CHECKING:
    from ..client import Client

DecryptInfo = Optional["ToDeviceDecryptInfo"]


@dataclass
class ToDeviceEvent(Event[ContentT]):
    client:     Parent["Client"] = field(repr=False)
    content:    ContentT
    sender:     UserId
    decryption: Runtime[DecryptInfo] = field(default=None, repr=False)

    @property
    def logger(self) -> MioLogger:
        return self.client

    async def _decrypted(self) -> "ToDeviceEvent":
        if not isinstance(self.content, Olm):
            return self

        decrypt = self.client.e2e._decrypt_olm_payload

        try:
            payload, verif_err = await decrypt(self)  # type: ignore
        except OlmDecryptionError as e:
            self.client.exception("Failed to decrypt {}", self)
            self.decryption = ToDeviceDecryptInfo(self, error=e)
            return self

        clear = type(self).from_dict({**self.source, **payload}, self.client)
        clear.decryption = ToDeviceDecryptInfo(self, payload, None, verif_err)

        if verif_err:
            self.client.warn("Error verifying decrypted event {}", clear)

        return clear


@dataclass
class ToDeviceDecryptInfo:
    original: "ToDeviceEvent"
    payload:  Optional[DictS] = field(default=None, repr=False)

    error:              Optional[OlmDecryptionError]   = None
    verification_error: Optional[OlmVerificationError] = None
