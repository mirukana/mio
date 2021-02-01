from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict

from ...errors import MioError
from .devices import Device

if TYPE_CHECKING:
    from .events import Olm


@dataclass(frozen=True)
class EncryptionModuleError(MioError):
    pass


@dataclass(frozen=True)
class VerificationError(EncryptionModuleError):
    pass


@dataclass(frozen=True)
class DecryptionError(EncryptionModuleError):
    pass


@dataclass(frozen=True)
class QueriedDeviceError(EncryptionModuleError):
    pass


@dataclass(frozen=True)
class QueriedDeviceUserIdMismatch(QueriedDeviceError):
    top_level_user_id: str
    info_user_id:      str


@dataclass(frozen=True)
class QueriedDeviceIdMismatch(QueriedDeviceError):
    top_level_device_id: str
    info_device_id:      str


@dataclass(frozen=True)
class QueriedDeviceEd25519Mismatch(QueriedDeviceError):
    saved_ed25519: str
    info_ed25519:  str


@dataclass(frozen=True)
class OlmDecryptionError(DecryptionError):
    pass


@dataclass(frozen=True)
class NoCipherForUs(OlmDecryptionError):
    our_curve25519: str
    ciphertext:     Dict[str, "Olm.Cipher"]


@dataclass(frozen=True)
class OlmSessionError(OlmDecryptionError):
    code: str


@dataclass(frozen=True)
class OlmVerificationError(VerificationError):
    pass


@dataclass(frozen=True)
class OlmPayloadSenderMismatch(OlmVerificationError):
    event_sender:   str
    payload_sender: str


@dataclass(frozen=True)
class OlmPayloadWrongReceiver(OlmVerificationError):
    intended_receiver: str
    our_user_id:       str


@dataclass(frozen=True)
class OlmPayloadWrongReceiverEd25519(OlmVerificationError):
    intended_ed25519: str
    our_ed25519:      str


@dataclass(frozen=True)
class OlmPayloadFromUnknownDevice(OlmVerificationError):
    known_sender_devices: Dict[str, "Device"]
    sender_ed25519:       str
    sender_curve25519:    str


@dataclass(frozen=True)
class MegolmDecryptionError(DecryptionError):
    pass


@dataclass(frozen=True)
class NoInboundGroupSessionToDecrypt(MegolmDecryptionError):
    room_id:           str
    sender_curve25519: str
    session_id:        str


@dataclass(frozen=True)
class MegolmSessionError(MegolmDecryptionError):
    code: str


@dataclass(frozen=True)
class PossibleReplayAttack(MegolmDecryptionError):
    pass


@dataclass(frozen=True)
class MegolmVerificationError(VerificationError):
    pass


@dataclass(frozen=True)
class MegolmPayloadWrongSender(MegolmVerificationError):
    starter_device_ed25519: str
    sender_curve25519:      str


@dataclass(frozen=True)
class InvalidSignedDict(EncryptionModuleError):
    pass


@dataclass(frozen=True)
class SignedDictMissingKey(InvalidSignedDict):
    key: str


@dataclass(frozen=True)
class SignedDictVerificationError(InvalidSignedDict):
    code: str
