import json
import logging as log
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import (
    TYPE_CHECKING, Any, Collection, Dict, List, Optional, Set, Tuple, Type,
)
from uuid import uuid4

import olm

from ...events import Content, TimelineEvent, ToDeviceEvent
from ...typing import EventId, RoomId, UserId
from ..client_module import JSONClientModule
from . import errors as err
from .devices import Device
from .events import Algorithm, EncryptionSettings, Megolm, Olm, RoomKey

if TYPE_CHECKING:
    from ...base_client import Client

# TODO: https://github.com/matrix-org/matrix-doc/pull/2732 (fallback OTK)
# TODO: protect against concurrency and saving sessions before sharing

Payload = Dict[str, Any]

MessageIndice = Dict[int, Tuple[EventId, datetime]]

InboundGroupSessionsType = Dict[
    # (room_id, sender_curve25519, session_id)
    Tuple[RoomId, str, str],
    # (session, sender_ed25519, message_indices)
    Tuple[olm.InboundGroupSession, str, MessageIndice],
]

# {room_id: (session, creation_date, encrypted_events_count)}
OutboundGroupSessionsType = Dict[
    RoomId, Tuple[olm.OutboundGroupSession, datetime, int],
]


def _olm_pickle(self, obj) -> str:
    return obj.pickle().decode()


def _olm_unpickle(value: str, parent, obj_type: Type) -> Any:
    return obj_type.from_pickle(value.encode())


@dataclass
class Encryption(JSONClientModule):
    dumpers = {
        **JSONClientModule.dumpers,  # type: ignore
        olm.Account: _olm_pickle,
        olm.Session: _olm_pickle,
        olm.OutboundGroupSession: _olm_pickle,
        olm.InboundGroupSession: _olm_pickle,
    }

    loaders = {
        **JSONClientModule.loaders,  # type: ignore
        olm.Account: partial(_olm_unpickle, obj_type=olm.Account),
        olm.Session: partial(_olm_unpickle, obj_type=olm.Session),
        olm.InboundGroupSession:
            partial(_olm_unpickle, obj_type=olm.InboundGroupSession),
        olm.OutboundGroupSession:
            partial(_olm_unpickle, obj_type=olm.OutboundGroupSession),
    }

    account:              olm.Account = field(default_factory=olm.Account)
    device_keys_uploaded: bool        = False

    devices: Dict[UserId, Dict[str, Device]] = field(default_factory=dict)

    # key = sender (inbound)/receiver (outbound) curve25519
    in_sessions:  Dict[str, List[olm.Session]] = field(default_factory=dict)
    out_sessions: Dict[str, List[olm.Session]] = field(default_factory=dict)

    in_group_sessions:  InboundGroupSessionsType  = field(default_factory=dict)
    out_group_sessions: OutboundGroupSessionsType = field(default_factory=dict)


    async def __ainit__(self) -> None:
        if not self.device_keys_uploaded:
            await self._upload_keys()
            await self.save()

        if not self.devices.get(self.client.user_id):
            await self.query_devices({self.client.user_id: []})
            await self.save()


    @property
    def own_device(self) -> Device:
        return self.devices[self.client.user_id][self.client.device_id]


    @classmethod
    def get_path(cls, parent: "Client", **kwargs) -> Path:
        return parent.path.parent / "encryption.json"


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

        await self.save()


    async def send_to_devices(
        self, events: Dict[Device, ToDeviceEvent],
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
            content = event.dict["content"]
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
        await self.save()


    async def handle_to_device_event(self, event: ToDeviceEvent) -> None:
        log.debug("%s got to-device event: %r", self.client.user_id, event)

        if not isinstance(event.content, RoomKey):
            return

        assert event.decryption
        assert isinstance(event.decryption.original.content, Olm)

        sender_curve25519 = event.decryption.original.content.sender_curve25519
        sender_ed25519    = event.decryption.payload["keys"]["ed25519"]
        content           = event.content

        ses = self.in_group_sessions
        key = (content.room_id, sender_curve25519, content.session_id)

        if key not in ses:
            session  = olm.InboundGroupSession(content.session_key)
            ses[key] = (session, sender_ed25519, {})
            await self.save()


    async def decrypt_olm_payload(
        self, event: ToDeviceEvent[Olm],
    ) -> Tuple[Payload, Optional[err.OlmVerificationError]]:
        # TODO: remove old sessions, unwedging, error handling?

        content      = event.content
        sender_curve = content.sender_curve25519
        our_curve    = self.own_device.curve25519
        cipher       = content.ciphertext.get(our_curve)

        if not cipher:
            raise err.NoCipherForUs(our_curve, content.ciphertext)

        is_prekey = cipher.type == Olm.Cipher.Type.prekey
        msg_class = olm.OlmPreKeyMessage if is_prekey else olm.OlmMessage
        message   = msg_class(cipher.body)

        for session in self.in_sessions.get(sender_curve, []):
            if is_prekey and not session.matches(message, sender_curve):
                continue

            try:
                payload = json.loads(session.decrypt(message))
            except olm.OlmSessionError as e:
                raise err.OlmSessionError(code=e.args[0])

            await self.save()
            try:
                return (self._verify_olm_payload(event, payload), None)
            except err.OlmVerificationError as e:
                return (payload, e)

        if not is_prekey:
            raise err.OlmDecryptionError()  # TODO: unwedge

        session = olm.InboundSession(self.account, message, sender_curve)
        self.account.remove_one_time_keys(session)
        await self.save()

        payload = json.loads(session.decrypt(message))
        self.in_sessions.setdefault(sender_curve, []).append(session)
        await self.save()

        try:
            return (self._verify_olm_payload(event, payload), None)
        except err.OlmVerificationError as e:
            return (payload, e)


    async def decrypt_megolm_payload(
        self, room_id: RoomId, event: TimelineEvent[Megolm],
    ) -> Tuple[Payload, Optional[err.MegolmVerificationError]]:

        content = event.content
        key     = (room_id, content.sender_curve25519, content.session_id)

        try:
            session, starter_ed25519, decrypted_indice = \
                self.in_group_sessions[key]
        except KeyError:
            # TODO: unwedge, request keys?
            raise err.NoInboundGroupSessionToDecrypt(*key)

        verif_error: Optional[err.MegolmVerificationError]
        verif_error = err.MegolmPayloadWrongSender(
            starter_ed25519, content.sender_curve25519,
        )

        for device in self.devices[event.sender].values():
            if device.curve25519 == content.sender_curve25519:
                if device.ed25519 == starter_ed25519:
                    verif_error = None  # TODO: device trust state

        try:
            json_payload, message_index = session.decrypt(content.ciphertext)
        except olm.OlmGroupSessionError as e:
            raise err.MegolmSessionError(code=e.args[0])

        known = message_index in decrypted_indice

        if known and decrypted_indice[message_index] != (event.id, event.date):
            raise err.PossibleReplayAttack()

        if not known:
            decrypted_indice[message_index] = (event.id, event.date)
            await self.save()

        return (json.loads(json_payload), verif_error)


    async def encrypt_room_event(
        self,
        room_id:   RoomId,
        for_users: Collection[UserId],
        settings:  EncryptionSettings,
        content:   Content,
    ) -> Megolm:

        default = (olm.OutboundGroupSession(), datetime.now(), 0)

        session, creation_date, encrypted_events_count = \
            self.out_group_sessions.get(room_id, default)

        # Do we have an existing non-expired OGSession for this room?
        if (
            room_id not in self.out_group_sessions or
            datetime.now() - creation_date > settings.sessions_max_age or
            encrypted_events_count > settings.sessions_max_messages
        ):
            # Create a corresponding InboundGroupSession:
            key        = (room_id, self.own_device.curve25519, session.id)
            our_ed     = self.own_device.ed25519
            in_session = olm.InboundGroupSession(session.session_key)

            self.in_group_sessions[key] = (in_session, our_ed, {})

            # Now share the outbound group session with everyone in the room:
            await self.query_devices({u: [] for u in for_users})

            room_key = RoomKey(
                algorithm   = Algorithm.megolm_v1,
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
            "type":    content.type,
            "content": content.dict,
            "room_id": room_id,
        }

        encrypted = Megolm(
            sender_curve25519 = self.own_device.curve25519,
            device_id         = self.client.device_id,
            session_id        = session.id,
            ciphertext        = session.encrypt(self._canonical_json(payload)),
        )

        msgs = encrypted_events_count + 1
        self.out_group_sessions[room_id] = (session, creation_date, msgs)
        await self.save()

        return encrypted


    async def drop_outbound_group_sessions(self, room_id: RoomId) -> None:
        self.out_group_sessions.pop(room_id, None)


    async def _upload_keys(self) -> None:
        device_keys = {
            "user_id":    self.client.user_id,
            "device_id":  self.client.device_id,
            "algorithms": [Algorithm.olm_v1.value, Algorithm.megolm_v1.value],
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

        self.device_keys_uploaded = True

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


    def _verify_olm_payload(
        self, event: ToDeviceEvent[Olm], payload: Payload,
    ) -> Payload:
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
            event.content.sender_curve25519 == self.own_device.curve25519
        ):
            return payload

        # TODO: verify device trust
        for device in self.devices[event.sender].values():
            if device.curve25519 == event.content.sender_curve25519:
                if device.ed25519 == payload_from_ed:
                    return payload

        raise err.OlmPayloadFromUnknownDevice(
            self.devices[event.sender],
            payload_from_ed,
            event.content.sender_curve25519,
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


    async def _encrypt_to_devices(
        self, content: Content, *devices: Device,
    ) -> Tuple[Dict[Device, Olm], Set[Device]]:

        sessions:         Dict[Device, olm.OutboundSession] = {}
        missing_sessions: Set[Device]                       = set()
        olms:             Dict[Device, Olm]                 = {}
        no_otks:          Set[Device]                       = set()

        for device in devices:
            try:
                sessions[device] = sorted(
                    self.out_sessions[device.curve25519],
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
                self.out_sessions.setdefault(
                    device.curve25519, [],
                ).append(sessions[device])

        payload_base: Dict[str, Any] = {
            "type":    content.type,
            "content": content.dict,
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
                sender_curve25519 = self.own_device.curve25519,
                ciphertext        = {device.curve25519: cipher},
            )

        await self.save()
        return (olms, no_otks)
