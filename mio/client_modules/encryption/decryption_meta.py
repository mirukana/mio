from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, Optional, Union

if TYPE_CHECKING:
    from .errors import VerificationError
    from .events import Megolm, Olm


@dataclass
class DecryptionMetadata:
    encrypted_source:   Union[None, "Olm", "Megolm"]  = None
    decrypted_payload:  Optional[Dict[str, Any]]      = None
    verification_error: Optional["VerificationError"] = None
