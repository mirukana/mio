from enum import Enum as _Enum


class OlmAlgorithm(_Enum):
    olm_v1 = "m.olm.v1.curve25519-aes-sha2"


class MegolmAlgorithm(_Enum):
    megolm_v1 = "m.megolm.v1.aes-sha2"


class Algorithm(_Enum):
    olm_v1    = "m.olm.v1.curve25519-aes-sha2"
    megolm_v1 = "m.megolm.v1.aes-sha2"
