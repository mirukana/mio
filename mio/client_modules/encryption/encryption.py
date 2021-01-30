import json
import logging as log
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import (
    TYPE_CHECKING, Any, Collection, Dict, List, Optional, Tuple, Union,
)

import olm
from aiofiles import open as aiopen

from ...events import Event, ToDeviceEvent
from .. import ClientModule
from . import errors as err
from .decryption_meta import DecryptionMetadata
from .devices import Device
from .events import Megolm, Olm, RoomKey

if TYPE_CHECKING:
    from ...base_client import BaseClient

# TODO: https://github.com/matrix-org/matrix-doc/pull/2732 (fallback OTK)
# TODO: protect against concurrency
# TODO: ensure logged in

Payload = Dict[str, Any]

# {index: (event_id, timestamp)}
MessageIndice = Dict[int, Tuple[Optional[str], Optional[float]]]

# {(room_id, sender_curve25519, session_id):
#  (session, sender_ed25519, message_indices)}
InboundGroupSessionsType = Dict[
    Tuple[str, str, str],
    Tuple[olm.InboundGroupSession, str, MessageIndice],
]


@dataclass
class Encryption(ClientModule):
    client:       "BaseClient"
    account_file: Optional[Path] = None

    uploaded_device_keys: bool = field(default=False, init=False)
    ready:                bool = field(default=False, init=False)

    devices: Dict[str, Dict[str, Device]] = \
        field(default_factory=dict, init=False)

    to_device_events: List[ToDeviceEvent] = \
        field(default_factory=list, repr=False, init=False)

    _account: Optional[olm.Account] = field(default=None, init=False)

    _inbound_sessions: Dict[str, List[olm.Session]] = \
        field(default_factory=dict, init=False)

    _inbound_group_sessions: InboundGroupSessionsType = \
        field(default_factory=dict, init=False)


    async def init(self, account_file: Union[None, str, Path] = None) -> None:
        if self.ready:
            raise RuntimeError("Encryption module was already initialized")

        if account_file:
            self.account_file = Path(account_file)

        if not self.account_file:
            raise ValueError("Encryption.account_file path not set")

        self.account_file.parent.mkdir(parents=True, exist_ok=True)

        if self.account_file.exists():
            await self._load()
        else:
            self._account = olm.Account()
            await self._save()

        if not self.uploaded_device_keys:
            await self._upload_keys()

        self.ready = True


    async def query_devices(
        self,
        for_users: Collection[str] = (),
        token:     Optional[str]   = None,
        timeout:   float           = 10,
    ) -> None:

        if not for_users:
            return

        log.info("Querying devices for %r", for_users)

        result = await self.client.send_json(
            method = "POST",
            path   = [*self.client.api, "keys", "query"],
            body   = {
                "device_keys": {user_id: [] for user_id in for_users},
                "token":       token,
                "timeout":     timeout * 1000,
            },
        )

        if result["failures"]:
            log.warning("Failed querying some devices: %s", result["failures"])

        for user_id, devices in result["device_keys"].items():
            for device_id, info in devices.items():
                try:
                    self._handle_queried_device(user_id, device_id, info)
                except err.QueriedDeviceError as e:
                    log.warning("Rejected queried device %r: %r", info, e)

        await self._save()


    async def upload_one_time_keys(self, currently_uploaded: int) -> None:
        assert self._account
        minimum = self._account.max_one_time_keys // 2

        if currently_uploaded >= minimum:
            return

        self._account.generate_one_time_keys(minimum - currently_uploaded)

        one_time_keys = {
            f"signed_curve25519:{keyid}": self._sign_dict({"key": key})
            for keyid, key in self._account.one_time_keys["curve25519"].items()
        }

        await self.client.send_json(
            method = "POST",
            path   = [*self.client.api, "keys", "upload"],
            body   = {"one_time_keys": one_time_keys},
        )

        self._account.mark_keys_as_published()
        await self._save()


    async def handle_to_device_event(self, event: ToDeviceEvent) -> None:
        self.to_device_events.append(event)

        if not isinstance(event, RoomKey):
            return

        assert event.decryption.encrypted_source
        encrypted = event.decryption.encrypted_source

        assert event.decryption.decrypted_payload
        sender_ed25519 = event.decryption.decrypted_payload["keys"]["ed25519"]

        ses = self._inbound_group_sessions
        key = (event.room_id, encrypted.sender_curve25519, event.session_id)

        if key not in ses:
            session  = olm.InboundGroupSession(event.session_key)
            ses[key] = (session, sender_ed25519, {})
            await self._save()


    async def decrypt_event(
        self, event: Union[Olm, Megolm], room_id: Optional[str] = None,
    ) -> Event:

        verif: Optional[err.VerificationError]

        if isinstance(event, Olm):
            payload, verif = await self._decrypt_olm_cipher(event)
        else:
            if not room_id:
                raise TypeError("room_id argument required for Megolm event")

            payload, verif = await self._decrypt_megolm_cipher(room_id, event)

        clear_source     = {**event.source, **payload}
        clear            = Event.subtype_from_source(clear_source)
        clear.decryption = DecryptionMetadata(event, payload, verif)

        if verif:
            log.warning("Error verifying decrypted event %r\n", clear)

        return clear


    async def _upload_keys(self) -> None:
        assert self._account

        device_keys = {
            "user_id":    self.client.auth.user_id,
            "device_id":  self.client.auth.device_id,
            "algorithms": [Olm.algorithm, Megolm.algorithm],
            "keys": {
                f"{kind}:{self.client.auth.device_id}": key
                for kind, key in self._account.identity_keys.items()
            },
        }

        device_keys = self._sign_dict(device_keys)

        result = await self.client.send_json(
            method = "POST",
            path   = [*self.client.api, "keys", "upload"],
            body   = {"device_keys": device_keys},
        )

        self.uploaded_device_keys = True
        await self._save()

        uploaded = result["one_time_key_counts"].get("signed_curve25519", 0)
        await self.upload_one_time_keys(uploaded)


    def _handle_queried_device(
        self, user_id: str, device_id: str, info: Dict[str, Any],
    ) -> None:

        auth = self.client.auth

        if user_id == auth.user_id and device_id == auth.device_id:
            return

        if info["user_id"] != user_id:
            raise err.QueriedDeviceUserIdMismatch(user_id, info["user_id"])

        if info["device_id"] != device_id:
            raise err.QueriedDeviceIdMismatch(device_id, info["device_id"])

        signer_ed25519 = info["keys"][f"ed25519:{device_id}"]
        self._verify_signed_dict(info, user_id, device_id, signer_ed25519)

        with suppress(KeyError):
            ed25519 = self.devices[user_id][device_id].ed25519
            if ed25519 != signer_ed25519:
                raise err.QueriedDeviceEd25519Mismatch(ed25519, signer_ed25519)

        self.devices.setdefault(user_id, {})[device_id] = Device(
            user_id,
            device_id,
            signer_ed25519,
            info["keys"][f"curve25519:{device_id}"],
            info["algorithms"],
            info.get("unsigned", {}).get("device_display_name"),
        )


    @staticmethod
    def _canonical_json(value: Any) -> bytes:
        # https://matrix.org/docs/spec/appendices#canonical-json

        return json.dumps(
            value, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
        ).encode("utf-8")


    def _sign_dict(self, dct: Dict[str, Any]) -> Dict[str, Any]:
        # https://matrix.org/docs/spec/appendices#signing-details

        dct        = dct.copy()
        signatures = dct.pop("signatures", {})
        unsigned   = dct.pop("unsigned", None)

        assert self._account
        signature = self._account.sign(self._canonical_json(dct))
        key       = f"ed25519:{self.client.auth.device_id}"

        signatures.setdefault(self.client.auth.user_id, {})[key] = signature

        dct["signatures"] = signatures
        if unsigned is not None:
            dct["unsigned"] = unsigned

        return dct


    async def _decrypt_olm_cipher(
        self, event: Olm,
    ) -> Tuple[Payload, Optional[err.OlmVerificationError]]:
        # TODO: remove old sessions, unwedging, error handling?

        assert self._account

        sender_curve = event.sender_curve25519
        own_key      = self._account.identity_keys["curve25519"]
        cipher       = event.ciphertext.get(own_key)

        if not cipher:
            raise err.NoCipherForUs(own_key, event.ciphertext)

        is_prekey = cipher.type == Olm.Cipher.Type.prekey
        msg_class = olm.OlmPreKeyMessage if is_prekey else olm.OlmMessage
        message   = msg_class(cipher.body)

        for session in self._inbound_sessions.get(event.sender_curve25519, []):
            if is_prekey and not session.matches(message, sender_curve):
                continue

            try:
                payload = json.loads(session.decrypt(message))
            except olm.OlmSessionError as e:
                raise err.OlmSessionError(code=e.args[0])

            await self._save()
            try:
                return (self._verify_olm_payload(event, payload), None)
            except err.OlmVerificationError as e:
                return (payload, e)

        if not is_prekey:
            raise err.OlmDecryptionError()  # TODO: unwedge

        assert self._account
        session = olm.InboundSession(self._account, message, sender_curve)
        self._account.remove_one_time_keys(session)
        await self._save()

        payload = json.loads(session.decrypt(message))
        self._inbound_sessions.setdefault(sender_curve, []).append(session)
        await self._save()

        try:
            return (self._verify_olm_payload(event, payload), None)
        except err.OlmVerificationError as e:
            return (payload, e)


    def _verify_olm_payload(self, event: Olm, payload: Payload) -> Payload:
        assert self._account
        assert self.client.auth.user_id
        our_user_id    = self.client.auth.user_id
        our_ed25519    = self._account.identity_keys["ed25519"]
        our_curve25519 = self._account.identity_keys["curve25519"]

        sender_devices = self.devices[event.sender]

        payload_from    = payload.get("sender", "")
        payload_to      = payload.get("recipient", "")
        payload_from_ed = payload.get("keys", {}).get("ed25519")
        payload_to_ed   = payload.get("recipient_keys", {}).get("ed25519", "")

        if payload_from != event.sender:
            raise err.OlmPayloadSenderMismatch(event.sender, payload_from)

        if payload_to != our_user_id:
            raise err.OlmPayloadWrongReceiver(payload_to, our_user_id)

        if payload_to_ed != our_ed25519:
            raise err.OlmPayloadWrongReceiverEd25519(
                payload_to_ed, our_ed25519,
            )

        if (
            payload_from == our_user_id and
            payload_from_ed  == our_ed25519 and
            event.sender_curve25519 == our_curve25519
        ):
            return payload

        # TODO: verify device trust
        for device in sender_devices.values():
            if device.curve25519 == event.sender_curve25519:
                if device.ed25519 == payload_from_ed:
                    return payload

        raise err.OlmPayloadFromUnknownDevice(
            sender_devices, payload_from_ed, event.sender_curve25519,
        )


    @staticmethod
    def _verify_signed_dict(
        dct:              Dict[str, Any],
        signer_user_id:   str,
        signer_device_id: str,
        signer_ed25519:   str,
    ) -> Dict[str, Any]:

        dct       = {k: v for k, v in dct.items() if k != "unsigned"}
        key_id    = f"ed25519:{signer_device_id}"
        signature = dct.pop("signatures")[signer_user_id][key_id]

        olm.ed25519_verify(
            signer_ed25519, Encryption._canonical_json(dct), signature,
        )
        return dct


    async def _decrypt_megolm_cipher(
        self, room_id: str, event: Megolm,
    ) -> Tuple[Payload, Optional[err.MegolmVerificationError]]:

        key = (room_id, event.sender_curve25519, event.session_id)
        try:
            session, starter_ed25519, decrypted_indices = \
                self._inbound_group_sessions[key]
        except KeyError:
            # TODO: unwedge, request keys?
            raise err.NoInboundGroupSessionToDecrypt(*key)

        verif_error: Optional[err.MegolmVerificationError]
        verif_error = err.MegolmPayloadWrongSender(
            starter_ed25519, event.sender_curve25519,
        )

        for device in self.devices[event.sender].values():
            if device.curve25519 == event.sender_curve25519:
                if device.ed25519 == starter_ed25519:
                    verif_error = None  # TODO: device trust state

        try:
            json_payload, message_index = session.decrypt(event.ciphertext)
        except olm.OlmGroupSessionError as e:
            raise err.MegolmSessionError(code=e.args[0])

        known     = message_index in decrypted_indices
        event_id  = event.event_id
        timestamp = event.date.timestamp() if event.date else None

        if known and decrypted_indices[message_index] != (event_id, timestamp):
            raise err.PossibleReplayAttack()

        if not known:
            decrypted_indices[message_index] = (event_id, timestamp)
            await self._save()

        return (json.loads(json_payload), verif_error)


    async def _load(self) -> None:
        async with aiopen(self.account_file) as file:  # type: ignore
            data = json.loads(await file.read())

        if data["user_id"] != self.client.auth.user_id:
            raise ValueError("Mismatched user_id for saved account")

        if data["device_id"] != self.client.auth.device_id:
            raise ValueError("Mismatched device_id for saved account")

        self.uploaded_device_keys = data["uploaded_device_keys"]

        self._account = olm.Account.from_pickle(data["olm_account"].encode())

        self._inbound_sessions = {
            key: [olm.Session.from_pickle(s.encode()) for s in sessions]
            for key, sessions in data["inbound_sessions"].items()
        }

        self._inbound_group_sessions = {
            tuple(json.loads(key)): (  # type: ignore
                olm.InboundGroupSession.from_pickle(session.encode()),
                sender_ed25519,
                {
                    int(i): (event_id, timestamp)
                    for i, (event_id, timestamp) in decrypted_indices.items()
                },
            )
            for key, (session, sender_ed25519, decrypted_indices)
            in data["inbound_group_sessions"].items()
        }

        self.devices = {
            user_id: {d["device_id"]: Device(**d) for d in devices.values()}
            for user_id, devices in data["devices"].items()
        }


    async def _save(self) -> None:
        assert self._account
        data = {
            "user_id":              self.client.auth.user_id,
            "device_id":            self.client.auth.device_id,
            "uploaded_device_keys": self.uploaded_device_keys,
            "olm_account":          self._account.pickle().decode(),

            "inbound_sessions": {
                key: [s.pickle().decode() for s in sessions]
                for key, sessions in self._inbound_sessions.items()
            },

            "inbound_group_sessions": {
                json.dumps(key):
                [session.pickle().decode(), sender_ed25519, decrypted_indices]
                for key, (session, sender_ed25519, decrypted_indices) in
                self._inbound_group_sessions.items()
            },

            "devices": {
                user_id: {d.device_id: asdict(d) for d in devices.values()}
                for user_id, devices in self.devices.items()
            },
        }

        async with aiopen(self.account_file, "w") as file:  # type: ignore
            await file.write(json.dumps(data, ensure_ascii=False, indent=4))
