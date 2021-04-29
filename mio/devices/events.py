# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from ..core.contents import ContentT
from ..core.data import Parent, Runtime
from ..core.events import Event
from ..core.ids import UserId
from ..core.utils import DictS, get_logger
from ..e2e.contents import Olm
from ..e2e.errors import OlmDecryptionError, OlmVerificationError

if TYPE_CHECKING:
    from ..client import Client

LOG = get_logger()

DecryptInfo = Optional["ToDeviceDecryptInfo"]


@dataclass
class ToDeviceEvent(Event[ContentT]):
    client:     Parent["Client"] = field(repr=False)
    content:    ContentT
    sender:     UserId
    decryption: Runtime[DecryptInfo] = field(default=None, repr=False)

    async def _decrypted(self) -> "ToDeviceEvent":
        if not isinstance(self.content, Olm):
            return self

        decrypt = self.client.e2e._decrypt_olm_payload

        try:
            payload, verif_err = await decrypt(self)  # type: ignore
        except OlmDecryptionError as e:
            LOG.exception("Failed to decrypt %r", self)
            self.decryption = ToDeviceDecryptInfo(self, error=e)
            return self

        clear = type(self).from_dict({**self.source, **payload}, self.client)
        clear.decryption = ToDeviceDecryptInfo(self, payload, None, verif_err)

        if verif_err:
            LOG.warning("Error verifying decrypted event %r\n", clear)

        return clear


@dataclass
class ToDeviceDecryptInfo:
    original: "ToDeviceEvent"
    payload:  Optional[DictS] = field(default=None, repr=False)

    error:              Optional[OlmDecryptionError]   = None
    verification_error: Optional[OlmVerificationError] = None
