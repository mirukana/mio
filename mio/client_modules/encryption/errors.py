from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict

from ...errors import MioError
from ...utils import Frozen
from .devices import Device

if TYPE_CHECKING:
    from .events import Olm


@dataclass
class EncryptionModuleError(MioError, Frozen):
    pass


@dataclass
class VerificationError(EncryptionModuleError):
    pass


@dataclass
class DecryptionError(EncryptionModuleError):
    pass


@dataclass
class QueriedDeviceError(EncryptionModuleError):
    pass


@dataclass
class QueriedDeviceUserIdMismatch(QueriedDeviceError):
    top_level_user_id: str
    info_user_id:      str


@dataclass
class QueriedDeviceIdMismatch(QueriedDeviceError):
    top_level_device_id: str
    info_device_id:      str


@dataclass
class QueriedDeviceEd25519Mismatch(QueriedDeviceError):
    saved_ed25519: str
    info_ed25519:  str


@dataclass
class OlmDecryptionError(DecryptionError):
    pass


@dataclass
class NoCipherForUs(OlmDecryptionError):
    our_curve25519: str
    ciphertext:     Dict[str, "Olm.Cipher"]


@dataclass
class OlmSessionError(OlmDecryptionError):
    code: str


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
class MegolmPayloadWrongSender(MegolmVerificationError):
    starter_device_ed25519: str
    sender_curve25519:      str


@dataclass
class InvalidSignedDict(EncryptionModuleError):
    pass


@dataclass
class SignedDictMissingKey(InvalidSignedDict):
    key: str


@dataclass
class SignedDictVerificationError(InvalidSignedDict):
    code: str
