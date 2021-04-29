# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Dict, Optional

from ..core.data import Runtime
from ..core.errors import MioError

if TYPE_CHECKING:
    from ..devices.device import Device
    from .contents import Olm


@dataclass
class E2EModuleError(MioError):
    pass


@dataclass
class VerificationError(E2EModuleError):
    pass


@dataclass
class DecryptionError(E2EModuleError):
    pass


@dataclass
class OlmDecryptionError(DecryptionError):
    pass


@dataclass
class NoCipherForUs(OlmDecryptionError):
    our_curve25519: str
    ciphertext:     Dict[str, "Olm.Cipher"]


@dataclass
class OlmSessionError(OlmDecryptionError):
    code:            str
    was_new_session: bool = False


@dataclass
class OlmExcpectedPrekey(OlmDecryptionError):
    pass


@dataclass
class OlmVerificationError(VerificationError):
    pass


@dataclass
class OlmPayloadSenderMismatch(OlmVerificationError):
    event_sender:   str
    payload_sender: str


@dataclass
class OlmPayloadWrongReceiver(OlmVerificationError):
    intended_receiver: str
    our_user_id:       str


@dataclass
class OlmPayloadWrongReceiverEd25519(OlmVerificationError):
    intended_ed25519: str
    our_ed25519:      str


@dataclass
class OlmPayloadFromBlockedDevice(OlmVerificationError):
    device: "Device"


@dataclass
class OlmPayloadFromUnknownDevice(OlmVerificationError):
    known_sender_devices: Dict[str, "Device"]
    sender_ed25519:       str
    sender_curve25519:    str


@dataclass
class MegolmDecryptionError(DecryptionError):
    pass


@dataclass
class NoInboundGroupSessionToDecrypt(MegolmDecryptionError):
    room_id:           str
    sender_curve25519: str
    session_id:        str


@dataclass
class MegolmSessionError(MegolmDecryptionError):
    code: str


@dataclass
class PossibleReplayAttack(MegolmDecryptionError):
    pass


@dataclass
class MegolmVerificationError(VerificationError):
    pass


@dataclass
class MegolmWrongSender(MegolmVerificationError):
    starter_device_ed25519: str
    sender_curve25519:      str


@dataclass
class MegolmFromUntrustedDevice(MegolmVerificationError):
    device: Optional["Device"]


@dataclass
class MegolmFromBlockedDevice(MegolmVerificationError):
    device: "Device"


@dataclass
class MegolmUntrustedDeviceInForwardChain(MegolmVerificationError):
    device: Optional["Device"]


@dataclass
class MegolmBlockedDeviceInForwardChain(MegolmVerificationError):
    device: "Device"


@dataclass
class InvalidSignedDict(E2EModuleError):
    pass


@dataclass
class SignedDictMissingKey(InvalidSignedDict):
    key: str


@dataclass
class SignedDictVerificationError(InvalidSignedDict):
    code: str


@dataclass
class SessionFileImportError(E2EModuleError):
    pass


@dataclass
class SessionFileMissingHeader(SessionFileImportError):
    pass


@dataclass
class SessionFileMissingFooter(SessionFileImportError):
    pass


@dataclass
class SessionFileInvalidBase64(SessionFileImportError):
    error_message: str


@dataclass
class SessionFileInvalidDataSize(SessionFileImportError):
    # Version, salt, init vector, counter, session data (variable length), HMAC
    minimum: ClassVar[Runtime[int]] = 1 + 16 + 16 + 4 + 1 + 32
    got:     int


@dataclass
class SessionFileUnsupportedVersion(SessionFileImportError):
    expected: ClassVar[Runtime[int]] = 1
    got:      int


@dataclass
class SessionFileInvalidHMAC(SessionFileImportError):
    expected: bytes
    got:      bytes


@dataclass
class SessionFileInvalidJSON(SessionFileImportError):
    data:          bytes
    error_message: str
