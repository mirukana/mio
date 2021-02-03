import json
import logging as log
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import (
    TYPE_CHECKING, Any, Collection, Dict, List, Optional, Set, Tuple, Union,
)
from uuid import uuid4

import olm
from pydantic import Field
from pydantic import validator as valid

from ...events import Event, RoomEvent, ToDeviceEvent
from ...typing import EventId, RoomId, UserId
from ...utils import AsyncInit, FileModel
from .. import ClientModule
from . import errors as err
from .devices import Device
from .events import EncryptionSettings, Megolm, Olm, RoomKey

# TODO: https://github.com/matrix-org/matrix-doc/pull/2732 (fallback OTK)
# TODO: protect against concurrency and saving sessions before sharing

if TYPE_CHECKING:
    from ...base_client import Client

Payload = Dict[str, Any]

MessageIndice = Dict[int, Tuple[Optional[EventId], Optional[datetime]]]

InboundGroupSessionsType = Dict[
    # room_id, sender_curve25519 and session_id separated by a \t
    # We use this weird format because json.dumps doesn't support tuple keys
    str,
    # (session, sender_ed25519, message_indices)
    Tuple[olm.InboundGroupSession, str, MessageIndice],
]

# {room_id: (session, creation_date, encrypted_events_count)}
OutboundGroupSessionsType = Dict[
    RoomId, Tuple[olm.OutboundGroupSession, datetime, int],
]


class Encryption(ClientModule, FileModel, AsyncInit):
    account: olm.Account                     = Field(None)
    devices: Dict[UserId, Dict[str, Device]] = {}

    # key = sender (inbound)/receiver (outbound) curve25519
    inbound_sessions:  Dict[str, List[olm.Session]] = {}
    outbound_sessions: Dict[str, List[olm.Session]] = {}

    inbound_group_sessions:  InboundGroupSessionsType  = {}
    outbound_group_sessions: OutboundGroupSessionsType = {}

    json_kwargs = {"exclude": {"client"}}


    class Config:
        arbitrary_types_allowed = True

        def olm_pickle(obj: Any) -> str:
            return obj.pickle().decode()

        json_encoders = {
            olm.Account:              olm_pickle,
            olm.Session:              olm_pickle,
            olm.OutboundGroupSession: olm_pickle,
            olm.InboundGroupSession:  olm_pickle,
        }


    @valid("account", pre=True)
    def _unpickle_account(cls, v):
        return olm.Account.from_pickle(v.encode()) if isinstance(v, str) else v


    @valid("inbound_sessions", "outbound_sessions", each_item=True, pre=True)
    def _unpickle_session(cls, v):
        return olm.Session.from_pickle(v.encode()) if isinstance(v, str) else v


    @valid("inbound_group_sessions", "outbound_group_sessions", pre=True)
    def _unpickle_group_session(cls, v, field):
        stype = olm.InboundGroupSession
        if field.name == "outbound_group_sessions":
            stype = olm.OutboundGroupSession

        def unpickle(s):
            return stype.from_pickle(s.encode()) if isinstance(s, str) else s

        return {
            key: (unpickle(session), sender_ed25519, decrypted_indice)
            for key, (session, sender_ed25519, decrypted_indice) in v.items()
        }


    async def __ainit__(self) -> None:
        if not self.account:
            self.account = olm.Account()
            await self._upload_keys()
            await self.query_devices({self.client.user_id: []})
            await self._save()


    @property
    def save_file(self) -> Path:
        return self.client.save_dir / "encryption.json"


    @classmethod
    async def load(cls, client: "Client") -> "Encryption":
        data = await cls._read_json(client.save_dir / "encryption.json")
        return await cls(client=client, **data)


    @property
    def own_device(self) -> Device:
        return self.devices[self.client.user_id][self.client.device_id]


    async def query_devices(
        self,
        # {user_id: [device_id]} - empty list = all devices for that user
        devices:      Dict[UserId, List[str]],
        update_token: Optional[str] = None,
        timeout:      float         = 10,
    ) -> None:

        if not update_token and any(d != [] for d in devices.values()):
            raise ValueError("No update_token to do partial device queries")

        if not update_token:
            devices = {
                u: d for u, d in devices.items() if u not in self.devices
            }

        if not devices:
            return

        log.info("Querying devices: %r", devices)

        result = await self.client.send_json(
            method = "POST",
            path   = [*self.client.api, "keys", "query"],
            body   = {
                "device_keys": devices,
                "token":       update_token,
                "timeout":     int(timeout * 1000),
            },
        )

        if result["failures"]:
            log.warning("Failed querying some devices: %s", result["failures"])

        for user_id, devs in result["device_keys"].items():
            for device_id, info in devs.items():
                try:
                    self._handle_queried_device(user_id, device_id, info)
                except (err.QueriedDeviceError, err.InvalidSignedDict) as e:
                    log.warning("Rejected queried device %r: %r", info, e)

        await self._save()


    async def send_to_devices(
        self, events: Dict[Device, Union[Olm, ToDeviceEvent]],
    ) -> None:

        if not events:
            return

        mtype = list(events.values())[0].type
        assert mtype

        if not all(e.type == mtype for e in events.values()):
            raise TypeError(f"Not all events have the same type: {events}")

        # We don't want to send events to the device we're using right now
        events.pop(self.own_device, None)

        msgs: Dict[UserId, Dict[str, Dict[str, Any]]] = {}

        for device, event in events.items():
            content = event.matrix["content"]
            msgs.setdefault(device.user_id, {})[device.device_id] = content

        # When all devices of an user are given with the same event,
        # compress the whole device dict into {"*": event}
        for user_id, devices in msgs.items():
            all_devices   = set(self.devices[user_id]) <= set(devices)
            device_events = list(devices.values())
            same_events   = all(e == device_events[0] for e in device_events)

            if all_devices and same_events:
                msgs[user_id] = {"*": device_events[0]}

        await self.client.send_json(
            method = "PUT",
            path   = [*self.client.api, "sendToDevice", mtype, str(uuid4())],
            body   = {"messages": msgs},
        )


    async def upload_one_time_keys(self, currently_uploaded: int) -> None:
        minimum = self.account.max_one_time_keys // 2

        if currently_uploaded >= minimum:
            return

        self.account.generate_one_time_keys(minimum - currently_uploaded)

        one_time_keys = {
            f"signed_curve25519:{keyid}": self._sign_dict({"key": key})
            for keyid, key in self.account.one_time_keys["curve25519"].items()
        }

        await self.client.send_json(
            method = "POST",
            path   = [*self.client.api, "keys", "upload"],
            body   = {"one_time_keys": one_time_keys},
        )

        self.account.mark_keys_as_published()
        await self._save()


    async def handle_to_device_event(self, event: ToDeviceEvent) -> None:
        log.debug("%s got to-device event: %r", self.client.user_id, event)

        if not isinstance(event, RoomKey):
            return

        assert event.encrypted_source
        sender_curve25519 = event.encrypted_source["content"]["sender_key"]

        assert event.decrypted_payload
        sender_ed25519 = event.decrypted_payload["keys"]["ed25519"]

        ses = self.inbound_group_sessions
        key = (event.room_id, sender_curve25519, event.session_id)

        if "\t".join(key) not in ses:
            session             = olm.InboundGroupSession(event.session_key)
            ses["\t".join(key)] = (session, sender_ed25519, {})
            await self._save()


    async def decrypt_event(
        self, event: Union[Olm, Megolm], room_id: Optional[RoomId] = None,
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

        clear.encrypted_source              = event.source
        clear.decrypted_payload             = payload
        clear.decryption_verification_error = verif

        if verif:
            log.warning("Error verifying decrypted event %r\n", clear)

        return clear


    async def encrypt_room_event(
        self,
        room_id:   RoomId,
        for_users: Collection[UserId],
        settings:  EncryptionSettings,
        event:     RoomEvent,
    ) -> Megolm:

        default = (olm.OutboundGroupSession(), datetime.now(), 0)

        session, creation_date, encrypted_events_count = \
            self.outbound_group_sessions.get(room_id, default)

        # Do we have an existing non-expired OGSession for this room?
        if (
            room_id not in self.outbound_group_sessions or
            datetime.now() - creation_date > settings.sessions_max_age or
            encrypted_events_count > settings.sessions_max_messages
        ):
            # Create a corresponding InboundGroupSession:
            tuple_key  = (room_id, self.own_device.curve25519, session.id)
            key        = "\t".join(tuple_key)
            our_ed     = self.own_device.ed25519
            in_session = olm.InboundGroupSession(session.session_key)

            self.inbound_group_sessions[key] = (in_session, our_ed, {})

            # Now share the outbound group session with everyone in the room:
            await self.query_devices({u: [] for u in for_users})

            room_key = RoomKey(
                algorithm   = RoomKey.Algorithm.megolm_v1_aes_sha2,
                room_id     = room_id,
                session_id  = session.id,
                session_key = session.session_key,
            )

            # TODO: device trust, e2e_algorithms
            olms, no_otks = await self._encrypt_to_devices(
                room_key,
                *[d for uid in for_users for d in self.devices[uid].values()],
            )

            if no_otks:
                log.warning(
                    "Didn't get one-time keys for %r, they will not receive"
                    "the megolm keys to decrypt %r",
                    no_otks, room_key,
                )

            await self.send_to_devices(olms)  # type: ignore

        payload = {
            "type":    event.type,
            "content": event.matrix["content"],
            "room_id": room_id,
        }

        encrypted = Megolm(
            sender_curve25519 = self.own_device.curve25519,
            device_id         = self.client.device_id,
            session_id        = session.id,
            ciphertext        = session.encrypt(self._canonical_json(payload)),
        )

        msgs = encrypted_events_count + 1
        self.outbound_group_sessions[room_id] = (session, creation_date, msgs)
        await self._save()

        return encrypted


    async def drop_outbound_group_sessions(self, room_id: RoomId) -> None:
        self.outbound_group_sessions.pop(room_id, None)


    async def _upload_keys(self) -> None:
        device_keys = {
            "user_id":    self.client.user_id,
            "device_id":  self.client.device_id,
            "algorithms": [Olm.algorithm, Megolm.algorithm],
            "keys": {
                f"{kind}:{self.client.device_id}": key
                for kind, key in self.account.identity_keys.items()
            },
        }

        device_keys = self._sign_dict(device_keys)

        result = await self.client.send_json(
            method = "POST",
            path   = [*self.client.api, "keys", "upload"],
            body   = {"device_keys": device_keys},
        )

        uploaded = result["one_time_key_counts"].get("signed_curve25519", 0)
        await self.upload_one_time_keys(uploaded)


    async def _claim_one_time_keys(
        self, *devices: Device, timeout: float = 10,
    ) -> Dict[Device, str]:

        if not devices:
            return {}

        log.info("Claiming keys for devices %r", devices)

        otk: Dict[str, Dict[str, str]] = {}
        for d in devices:
            otk.setdefault(d.user_id, {})[d.device_id] = "signed_curve25519"

        result = await self.client.send_json(
            method = "POST",
            path   = [*self.client.api, "keys", "claim"],
            body   = {"timeout": int(timeout * 1000), "one_time_keys": otk},
        )

        if result["failures"]:
            log.warning("Failed claiming some keys: %s", result["failures"])

        valided: Dict[Device, str] = {}

        for user_id, device_keys in result["one_time_keys"].items():
            for device_id, keys in device_keys.items():
                for key_dict in keys.copy().values():
                    dev = self.devices[user_id][device_id]

                    if "key" not in key_dict:
                        log.warning("No key for %r claim: %r", dev, key_dict)
                        continue

                    try:
                        self._verify_signed_dict(
                            key_dict, user_id, device_id, dev.ed25519,
                        )
                    except err.InvalidSignedDict as e:
                        log.warning(
                            "Rejected %r claimed key %r: %r", dev, key_dict, e,
                        )
                    else:
                        valided[dev] = key_dict["key"]

        return valided


    def _handle_queried_device(
        self, user_id: UserId, device_id: str, info: Dict[str, Any],
    ) -> None:

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
            user_id        = user_id,
            device_id      = device_id,
            ed25519        = signer_ed25519,
            curve25519     = info["keys"][f"curve25519:{device_id}"],
            e2e_algorithms = info["algorithms"],
            display_name   =
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

        signature = self.account.sign(self._canonical_json(dct))
        key       = f"ed25519:{self.client.device_id}"

        signatures.setdefault(self.client.user_id, {})[key] = signature

        dct["signatures"] = signatures
        if unsigned is not None:
            dct["unsigned"] = unsigned

        return dct


    async def _decrypt_olm_cipher(
        self, event: Olm,
    ) -> Tuple[Payload, Optional[err.OlmVerificationError]]:
        # TODO: remove old sessions, unwedging, error handling?

        sender_curve = event.sender_curve25519
        our_curve    = self.own_device.curve25519
        cipher       = event.ciphertext.get(our_curve)

        if not cipher:
            raise err.NoCipherForUs(our_curve, event.ciphertext)

        is_prekey = cipher.type == Olm.Cipher.Type.prekey
        msg_class = olm.OlmPreKeyMessage if is_prekey else olm.OlmMessage
        message   = msg_class(cipher.body)

        for session in self.inbound_sessions.get(event.sender_curve25519, []):
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

        session = olm.InboundSession(self.account, message, sender_curve)
        self.account.remove_one_time_keys(session)
        await self._save()

        payload = json.loads(session.decrypt(message))
        self.inbound_sessions.setdefault(sender_curve, []).append(session)
        await self._save()

        try:
            return (self._verify_olm_payload(event, payload), None)
        except err.OlmVerificationError as e:
            return (payload, e)


    def _verify_olm_payload(self, event: Olm, payload: Payload) -> Payload:
        payload_from    = payload.get("sender", "")
        payload_to      = payload.get("recipient", "")
        payload_from_ed = payload.get("keys", {}).get("ed25519")
        payload_to_ed   = payload.get("recipient_keys", {}).get("ed25519", "")

        if payload_from != event.sender:
            raise err.OlmPayloadSenderMismatch(event.sender, payload_from)

        if payload_to != self.client.user_id:
            raise err.OlmPayloadWrongReceiver(payload_to, self.client.user_id)

        if payload_to_ed != self.own_device.ed25519:
            raise err.OlmPayloadWrongReceiverEd25519(
                payload_to_ed, self.own_device.ed25519,
            )

        if (
            payload_from == self.client.user_id and
            payload_from_ed  == self.own_device.ed25519 and
            event.sender_curve25519 == self.own_device.curve25519
        ):
            return payload

        # TODO: verify device trust
        for device in self.devices[event.sender].values():
            if device.curve25519 == event.sender_curve25519:
                if device.ed25519 == payload_from_ed:
                    return payload

        raise err.OlmPayloadFromUnknownDevice(
            self.devices[event.sender],
            payload_from_ed,
            event.sender_curve25519,
        )


    @staticmethod
    def _verify_signed_dict(
        dct:              Dict[str, Any],
        signer_user_id:   UserId,
        signer_device_id: str,
        signer_ed25519:   str,
    ) -> Dict[str, Any]:
        dct       = {k: v for k, v in dct.items() if k != "unsigned"}
        key_id    = f"ed25519:{signer_device_id}"

        try:
            signature = dct.pop("signatures")[signer_user_id][key_id]
        except KeyError as e:
            raise err.SignedDictMissingKey(e.args[0])

        try:
            olm.ed25519_verify(
                signer_ed25519, Encryption._canonical_json(dct), signature,
            )
        except olm.OlmVerifyError as e:
            raise err.SignedDictVerificationError(e.args[0])

        return dct


    async def _decrypt_megolm_cipher(
        self, room_id: RoomId, event: Megolm,
    ) -> Tuple[Payload, Optional[err.MegolmVerificationError]]:

        tuple_key = (room_id, event.sender_curve25519, event.session_id)

        try:
            session, starter_ed25519, decrypted_indice = \
                self.inbound_group_sessions["\t".join(tuple_key)]
        except KeyError:
            # TODO: unwedge, request keys?
            raise err.NoInboundGroupSessionToDecrypt(*tuple_key)

        verif_error: Optional[err.MegolmVerificationError]
        verif_error = err.MegolmPayloadWrongSender(
            starter_ed25519, event.sender_curve25519,
        )

        if not event.sender:
            raise err.MegolmMissingSender()

        for device in self.devices[event.sender].values():
            if device.curve25519 == event.sender_curve25519:
                if device.ed25519 == starter_ed25519:
                    verif_error = None  # TODO: device trust state

        try:
            json_payload, message_index = session.decrypt(event.ciphertext)
        except olm.OlmGroupSessionError as e:
            raise err.MegolmSessionError(code=e.args[0])

        known    = message_index in decrypted_indice
        event_id = event.event_id
        date     = event.date

        if known and decrypted_indice[message_index] != (event_id, date):
            raise err.PossibleReplayAttack()

        if not known:
            decrypted_indice[message_index] = (event_id, date)
            await self._save()

        return (json.loads(json_payload), verif_error)


    async def _encrypt_to_devices(
        self, event: ToDeviceEvent, *devices: Device,
    ) -> Tuple[Dict[Device, Olm], Set[Device]]:

        sessions:         Dict[Device, olm.OutboundSession] = {}
        missing_sessions: Set[Device]                       = set()
        olms:             Dict[Device, Olm]                 = {}
        no_otks:          Set[Device]                       = set()

        for device in devices:
            try:
                sessions[device] = sorted(
                    self.outbound_sessions[device.curve25519],
                    key=lambda session: session.id,
                )[0]
            except (KeyError, IndexError):
                missing_sessions.add(device)

        new_otks = await self._claim_one_time_keys(*missing_sessions)

        for device in missing_sessions:
            if device not in new_otks:
                no_otks.add(device)
            else:
                sessions[device] = olm.OutboundSession(
                    self.account, device.curve25519, new_otks[device],
                )
                self.outbound_sessions.setdefault(
                    device.curve25519, [],
                ).append(sessions[device])

        payload_base: Dict[str, Any] = {
            "type":    event.type,
            "content": event.matrix["content"],
            "sender":  self.client.user_id,
            "keys":    {"ed25519": self.own_device.ed25519},
        }

        for device, session in sessions.items():
            payload = {
                **payload_base,
                "recipient":      device.user_id,
                "recipient_keys": {"ed25519": device.ed25519},
            }

            msg    = session.encrypt(self._canonical_json(payload))
            cipher = Olm.Cipher(type=msg.message_type, body=msg.ciphertext)

            olms[device] = Olm(
                sender            = self.client.user_id,
                sender_curve25519 = self.own_device.curve25519,
                ciphertext        = {device.curve25519: cipher},
            )

        await self._save()
        return (olms, no_otks)
