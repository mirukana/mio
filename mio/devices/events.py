from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from ..core.contents import ContentT
from ..core.data import Parent, Runtime
from ..core.events import Event
from ..core.types import DictS, UserId
from ..core.utils import get_logger
from ..e2e.contents import Olm
from ..e2e.errors import OlmVerificationError

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

    async def decrypted(self) -> "ToDeviceEvent":
        if not isinstance(self.content, Olm):
            return self

        decrypt            = self.client.e2e.decrypt_olm_payload
        payload, verif_err = await decrypt(self)  # type: ignore

        clear = type(self).from_dict({**self.source, **payload}, self.client)
        clear.decryption = ToDeviceDecryptInfo(self, payload, verif_err)

        if verif_err:
            LOG.warning("Error verifying decrypted event %r\n", clear)

        return clear


@dataclass
class ToDeviceDecryptInfo:
    original:           "ToDeviceEvent"
    payload:            DictS
    verification_error: Optional[OlmVerificationError] = None
