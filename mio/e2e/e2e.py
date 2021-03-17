import json
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import (
    TYPE_CHECKING, Any, Collection, Dict, List, Optional, Set, Tuple, Type,
)

import olm

from ..core.contents import EventContent
from ..core.types import EventId, RoomId, UserId
from ..core.utils import get_logger
from ..devices.device import Device
from ..devices.events import ToDeviceEvent
from ..module import JSONClientModule
from ..rooms.contents.settings import Encryption
from ..rooms.timeline import TimelineEvent
from . import Algorithm
from . import errors as err
from .contents import GroupSessionInfo, Megolm, Olm

if TYPE_CHECKING:
    from ..client import Client

# TODO: https://github.com/matrix-org/matrix-doc/pull/2732 (fallback OTK)
# TODO: protect against concurrency and saving sessions before sharing

LOG = get_logger()

Payload = Dict[str, Any]

MessageIndice = Dict[int, Tuple[EventId, datetime]]

InboundGroupSessionsType = Dict[
    # (room_id, sender_curve25519, session_id)
    Tuple[RoomId, str, str],
    # (session, sender_ed25519, message_indices)
    Tuple[olm.InboundGroupSession, str, MessageIndice],
]

# {user_id: {device_id}}
SharedTo = Dict[UserId, Set[str]]

# {room_id: (session, creation_date, encrypted_events_count, shared_to)}
OutboundGroupSessionsType = Dict[
    RoomId, Tuple[olm.OutboundGroupSession, datetime, int, SharedTo],
]


def _olm_pickle(self, obj) -> str:
    return obj.pickle().decode()


def _olm_unpickle(value: str, parent, obj_type: Type) -> Any:
    return obj_type.from_pickle(value.encode())


@dataclass
class E2E(JSONClientModule):
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

    # key = sender (inbound)/receiver (outbound) curve25519
    in_sessions:  Dict[str, List[olm.Session]] = field(default_factory=dict)
    out_sessions: Dict[str, List[olm.Session]] = field(default_factory=dict)

    in_group_sessions:  InboundGroupSessionsType  = field(default_factory=dict)
    out_group_sessions: OutboundGroupSessionsType = field(default_factory=dict)


    async def __ainit__(self) -> None:
        if not self.device_keys_uploaded:
            await self._upload_keys()
            await self.save()


    @property
    def device(self) -> "Device":
        return self.client.devices.current


    @classmethod
    def get_path(cls, parent: "Client", **kwargs) -> Path:
        return parent.path.parent / "e2e.json"


    async def upload_one_time_keys(self, currently_uploaded: int) -> None:
        minimum = self.account.max_one_time_keys // 2

        if currently_uploaded >= minimum:
            return

        self.account.generate_one_time_keys(minimum - currently_uploaded)

        one_time_keys = {
            f"signed_curve25519:{key_id}": self._sign_dict({"key": key})
            for key_id, key in self.account.one_time_keys["curve25519"].items()
        }

        await self.client.send_json(
            method = "POST",
            path   = [*self.client.api, "keys", "upload"],
            body   = {"one_time_keys": one_time_keys},
        )

        self.account.mark_keys_as_published()
        await self.save()


    async def decrypt_olm_payload(
        self, event: ToDeviceEvent[Olm],
    ) -> Tuple[Payload, Optional[err.OlmVerificationError]]:
        # TODO: remove old sessions, unwedging, error handling?

        content      = event.content
        sender_curve = content.sender_curve25519
        our_curve    = self.device.curve25519
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

        verif_err: Optional[err.MegolmVerificationError]
        verif_err = err.MegolmPayloadWrongSender(
            starter_ed25519, content.sender_curve25519,
        )

        for device in self.client.devices[event.sender].values():
            if device.curve25519 == content.sender_curve25519:
                if device.ed25519 == starter_ed25519:
                    if device.trusted is False:
                        verif_err = err.MegolmPayloadFromBlockedDevice(device)
                    else:
                        verif_err = None

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

        return (json.loads(json_payload), verif_err)


    async def encrypt_room_event(
        self,
        room_id:   RoomId,
        for_users: Collection[UserId],
        settings:  Encryption,
        content:   EventContent,
    ) -> Megolm:

        for_users = set(for_users)

        default: tuple = (olm.OutboundGroupSession(), datetime.now(), 0, {})

        session, creation_date, encrypted_events_count, shared_to = \
            self.out_group_sessions.get(room_id, default)

        # If we have no existing non-expired OutbondGroupSession for this room:
        if (
            room_id not in self.out_group_sessions or
            datetime.now() - creation_date > settings.sessions_max_age or
            encrypted_events_count > settings.sessions_max_messages
        ):
            # Create a corresponding InboundGroupSession:
            key        = (room_id, self.device.curve25519, session.id)
            our_ed     = self.device.ed25519
            in_session = olm.InboundGroupSession(session.session_key)

            self.in_group_sessions[key] = (in_session, our_ed, {})

        # Make sure first we know about all the devices to send session to:
        await self.client.devices.ensure_tracked(for_users)

        in_need = {
            device
            for user_id in for_users
            for device in self.client.devices[user_id].values()

            if device.trusted is not False and
            device.device_id not in shared_to.get(user_id, set())
        }

        await self._share_out_group_session(room_id, session, in_need)

        for device in in_need:
            shared_to.setdefault(device.user_id, set()).add(device.device_id)

        # Now that everyone else has our session, we can send the event
        payload = {
            "type":    content.type,
            "content": content.dict,
            "room_id": room_id,
        }

        encrypted = Megolm(
            sender_curve25519 = self.device.curve25519,
            device_id         = self.client.device_id,
            session_id        = session.id,
            ciphertext        = session.encrypt(self._canonical_json(payload)),
        )

        self.out_group_sessions[room_id] = (
            session, creation_date, encrypted_events_count + 1, shared_to,
        )
        await self.save()

        return encrypted


    async def drop_outbound_group_session(self, room_id: RoomId) -> None:
        self.out_group_sessions.pop(room_id, None)
        await self.save()


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

        LOG.info("Claiming keys for devices %r", devices)

        otk: Dict[str, Dict[str, str]] = {}
        for d in devices:
            otk.setdefault(d.user_id, {})[d.device_id] = "signed_curve25519"

        result = await self.client.send_json(
            method = "POST",
            path   = [*self.client.api, "keys", "claim"],
            body   = {"timeout": int(timeout * 1000), "one_time_keys": otk},
        )

        if result["failures"]:
            LOG.warning("Failed claiming some keys: %s", result["failures"])

        valided: Dict[Device, str] = {}

        for user_id, device_keys in result["one_time_keys"].items():
            for device_id, keys in device_keys.items():
                for key_dict in keys.copy().values():
                    dev = self.client.devices[user_id][device_id]

                    if "key" not in key_dict:
                        LOG.warning("No key for %r claim: %r", dev, key_dict)
                        continue

                    try:
                        self._verify_signed_dict(
                            key_dict, user_id, device_id, dev.ed25519,
                        )
                    except err.InvalidSignedDict as e:
                        LOG.warning(
                            "Rejected %r claimed key %r: %r", dev, key_dict, e,
                        )
                    else:
                        valided[dev] = key_dict["key"]

        return valided


    async def _share_out_group_session(
        self,
        room_id: RoomId,
        session: olm.OutboundGroupSession,
        to:      Set[Device],
    ) -> None:

        to = {d for d in to if d is not self.device}

        if not to:
            return

        info = GroupSessionInfo(
            algorithm   = Algorithm.megolm_v1,
            room_id     = room_id,
            session_id  = session.id,
            session_key = session.session_key,
        )

        olms, no_otks = await self.client.devices._encrypt(info, *to)

        if no_otks:
            LOG.warning(
                "Didn't get any one-time keys for %r, they won't receive "
                "the group session keys to decrypt %r!",
                no_otks, info,
            )

        await self.client.devices.send(olms)  # type: ignore


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

        if payload_to_ed != self.device.ed25519:
            raise err.OlmPayloadWrongReceiverEd25519(
                payload_to_ed, self.device.ed25519,
            )

        if (
            payload_from == self.client.user_id and
            payload_from_ed  == self.device.ed25519 and
            event.content.sender_curve25519 == self.device.curve25519
        ):
            return payload

        for device in self.client.devices[event.sender].values():
            if device.curve25519 == event.content.sender_curve25519:
                if device.ed25519 == payload_from_ed:
                    if device.trusted is False:
                        raise err.OlmPayloadFromBlockedDevice(device)
                    return payload

        raise err.OlmPayloadFromUnknownDevice(
            self.client.devices[event.sender],
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
                signer_ed25519, E2E._canonical_json(dct), signature,
            )
        except olm.OlmVerifyError as e:
            raise err.SignedDictVerificationError(e.args[0])

        return dct
