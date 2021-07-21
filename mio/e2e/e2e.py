# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

import json
from asyncio import Future, ensure_future
from binascii import Error as BinAsciiError
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial
from typing import (
    Any, AsyncIterator, Callable, ClassVar, Collection, Deque, Dict, List,
    Optional, Set, Tuple, Type, Union,
)

import olm
from aiopath import AsyncPath
from Cryptodome import Random
from Cryptodome.Cipher import AES
from Cryptodome.Hash import HMAC, SHA256, SHA512
from Cryptodome.Protocol.KDF import PBKDF2
from Cryptodome.Util import Counter
from unpaddedbase64 import decode_base64, encode_base64

from ..core.contents import EventContent
from ..core.data import Runtime
from ..core.ids import MXC, EventId, RoomId, UserId
from ..devices.device import Device
from ..devices.events import ToDeviceEvent
from ..module import JSONClientModule
from ..rooms.contents.settings import Encryption
from ..rooms.timeline import TimelineEvent
from . import Algorithm, MegolmAlgorithm
from . import errors as err
from .contents import (
    CancelGroupSessionRequest, Dummy, EncryptedMediaInfo,
    ForwardedGroupSessionInfo, GroupSessionInfo, GroupSessionRequest, Megolm,
    Olm,
)

# TODO: protect against concurrency and saving sessions before sharing

Payload = Dict[str, Any]

# (room_id, sender_curve25519, session_id)
InboundGroupSessionKey = Tuple[RoomId, str, str]

MessageIndice = Dict[int, Tuple[EventId, datetime]]

InGroupSessionsType = Dict[
    InboundGroupSessionKey,
    # (session, sender_ed25519, message_indices, curve25519_forwarding_chain)
    Tuple[olm.InboundGroupSession, str, MessageIndice, List[str]],
]

# {user_id: {device_id}}
SharedTo = Dict[UserId, Set[str]]

# {room_id: (session, creation_date, encrypted_events_count, shared_to)}
OutGroupSessionsType = Dict[
    RoomId, Tuple[olm.OutboundGroupSession, datetime, int, SharedTo],
]

SessionRequestsType = Dict[
    InboundGroupSessionKey,
    Tuple[GroupSessionRequest, Set[UserId]],  # set: users we sent request to
]

DeviceChain = List[Union[Device, str]]

SESSION_FILE_HEADER = "-----BEGIN MEGOLM SESSION DATA-----"
SESSION_FILE_FOOTER = "-----END MEGOLM SESSION DATA-----"


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

    _max_sessions_per_device: ClassVar[Runtime[int]] = 5

    _account: olm.Account = field(default_factory=olm.Account)

    # key: peer device curve25519 - last session: last one that decrypted a msg
    _sessions: Dict[str, Deque[olm.Session]] = field(default_factory=dict)

    _in_group_sessions:  InGroupSessionsType  = field(default_factory=dict)
    _out_group_sessions: OutGroupSessionsType = field(default_factory=dict)

    _recovered_olm_this_sync: Set[UserId]         = field(default_factory=set)
    _sent_session_requests:   SessionRequestsType = field(default_factory=dict)

    _forward_tasks: Runtime[Dict[str, Future]] = field(
        init=False, default_factory=dict,
    )


    @property
    def path(self) -> AsyncPath:
        return self.client.path.parent / "e2e.json"


    @property
    def device(self) -> "Device":
        return self.client.devices.current


    # Public methods

    async def export_sessions(
        self,
        passphrase:     str,
        _json_modifier: Optional[Callable[[str], str]] = None,
    ) -> str:
        sessions = []

        for key, value in self._in_group_sessions.items():
            self.client.debug("Structuring for export: {}, {}", key, value)

            room_id, sender_curve25519, session_id    = key
            session, sender_ed25519, _, forward_chain = value

            first_index = session.first_known_index

            sessions.append({
                "algorithm": Algorithm.megolm_v1.value,
                "forwarding_curve25519_key_chain": forward_chain,
                "room_id": room_id,
                "sender_key": sender_curve25519,
                "sender_claimed_keys": {"ed25519": sender_ed25519},
                "session_id": session_id,
                "session_key": session.export_session(first_index),
            })

        self.client.debug("Structured sessions for export: {}", sessions)

        salt  = Random.new().read(16)  # 16 byte/128 bit salt
        count = 100_000

        derived_key = PBKDF2(  # 64 byte / 512 bit key
            passphrase, salt, dkLen=64, count=count, hmac_hash_module=SHA512,
        )
        aes256_key = derived_key[:32]
        hmac_key   = derived_key[32:]

        init_vector    = int.from_bytes(Random.new().read(16), byteorder="big")
        init_vector   &= ~(1 << 63)  # set bit 63 to 0
        counter        = Counter.new(128, initial_value=init_vector)
        cipher         = AES.new(aes256_key, AES.MODE_CTR, counter=counter)
        json_modifier  = _json_modifier or (lambda data: data)

        data = b"".join((
            bytes([1]),  # Export format version
            salt,
            init_vector.to_bytes(length=16, byteorder="big"),
            count.to_bytes(length=4, byteorder="big"),
            cipher.encrypt(json_modifier(json.dumps(sessions)).encode()),
        ))

        base64 = encode_base64(b"".join((
            data, HMAC.new(hmac_key, data, SHA256).digest(),
        )))

        return "\n".join((SESSION_FILE_HEADER, base64, SESSION_FILE_FOOTER))


    async def import_sessions(self, data: str, passphrase: str) -> None:
        client = self.client
        data   = data.replace("\n", "")

        if not data.startswith(SESSION_FILE_HEADER):
            raise err.SessionFileMissingHeader()

        if not data.endswith(SESSION_FILE_FOOTER):
            raise err.SessionFileMissingFooter()

        data = data[len(SESSION_FILE_HEADER): -len(SESSION_FILE_FOOTER)]

        try:
            decoded = decode_base64(data)
        except BinAsciiError as e:
            raise err.SessionFileInvalidBase64(next(iter(e.args), ""))

        if len(decoded) < err.SessionFileInvalidDataSize.minimum:
            raise err.SessionFileInvalidDataSize(len(decoded))

        version       = decoded[0]  # indexing single byte returns an int
        salt          = decoded[1:17]
        init_vector   = int.from_bytes(decoded[17:33], byteorder="big")
        count         = int.from_bytes(decoded[33:37], byteorder="big")
        session_data  = decoded[37:-32]
        expected_hmac = decoded[-32:]

        if version != 1:
            raise err.SessionFileUnsupportedVersion(version)

        derived_key = PBKDF2(
            passphrase, salt, dkLen=64, count=count, hmac_hash_module=SHA512,
        )
        aes256_key = derived_key[:32]
        hmac       = HMAC.new(derived_key[32:], decoded[:-32], SHA256).digest()

        if expected_hmac != hmac:
            raise err.SessionFileInvalidHMAC(expected_hmac, hmac)

        counter       = Counter.new(128, initial_value=init_vector)
        cipher        = AES.new(aes256_key, AES.MODE_CTR, counter=counter)
        json_sessions = cipher.decrypt(session_data)

        self.client.debug("Importing sessions from {}", json_sessions)

        try:
            sessions = json.loads(json_sessions)
        except json.JSONDecodeError as e:
            raise err.SessionFileInvalidJSON(json_sessions, e.args[0])

        if not isinstance(sessions, list):
            raise err.SessionFileInvalidJSON(json_sessions, "expected list")

        imported: List[InboundGroupSessionKey] = []

        for session in sessions:
            try:
                if session["algorithm"] != Algorithm.megolm_v1.value:
                    client.warn("Skipping {}, unsupported algorithm", session)
                    continue

                storage_key = (
                    session["room_id"],
                    session["sender_key"],  # curve25519
                    session["session_id"],
                )

                existing        = self._in_group_sessions.get(storage_key)
                skey            = session["session_key"]
                rebuilt_session = olm.InboundGroupSession.import_session(skey)

                if (
                    existing and
                    rebuilt_session.first_known_index <=
                    existing[0].first_known_index
                ):
                    client.warn(
                        "Skipping {}, older version of {}", session, existing,
                    )
                    continue

                self._in_group_sessions[storage_key] = (
                    rebuilt_session,
                    session["sender_claimed_keys"]["ed25519"],
                    {},  # message_indices
                    session["forwarding_curve25519_key_chain"],
                )
                imported.append(storage_key)
            except (TypeError, KeyError, olm.OlmGroupSessionError):
                client.exception("Skipping {}, import failure", session)

        if imported:
            await self.save()
            await self.client.rooms._retry_decrypt(*imported)


    # Methods called from outside this module but not for users usage

    async def _upload_one_time_keys(self, currently_uploaded: int) -> None:
        minimum = self._account.max_one_time_keys // 2
        self.client.debug("{}/{} uploaded OTK", currently_uploaded, minimum)

        if currently_uploaded >= minimum:
            return

        self._account.generate_one_time_keys(minimum - currently_uploaded)

        data = {
            "one_time_keys": {
                f"signed_curve25519:{key_id}": self._sign_dict({"key": key})
                for key_id, key in
                self._account.one_time_keys["curve25519"].items()
            },
        }

        await self.net.post(self.net.api / "keys" / "upload", data)
        self._account.mark_keys_as_published()
        await self.save()


    async def _decrypt_olm_payload(
        self, event: ToDeviceEvent[Olm],
    ) -> Tuple[Payload, Optional[err.OlmVerificationError]]:

        content      = event.content
        sender_curve = content.sender_curve25519
        our_curve    = self.device.curve25519
        cipher       = content.ciphertext.get(our_curve)

        if not cipher:
            await self._recover_from_undecryptable_olm(event)
            raise err.NoCipherForUs(our_curve, content.ciphertext)

        is_prekey = cipher.type == Olm.Cipher.Type.prekey
        msg_class = olm.OlmPreKeyMessage if is_prekey else olm.OlmMessage
        message   = msg_class(cipher.body)

        deque: Deque[olm.Session] = Deque(maxlen=self._max_sessions_per_device)
        sessions                  = self._sessions.get(sender_curve, deque)

        for i, session in enumerate(sessions):
            if is_prekey and not session.matches(message, sender_curve):
                continue

            try:
                decrypted = session.decrypt(message)
            except olm.OlmSessionError as e:
                await self._recover_from_undecryptable_olm(event)
                raise err.OlmSessionError(code=e.args[0])

            # When sending olm messages, we'll want to use the last session
            # for which a message has been successfully decrypted
            del sessions[i]
            sessions.append(session)
            await self.save()

            payload = json.loads(decrypted)  # TODO catch json error

            try:
                return (self._verify_olm_payload(event, payload), None)
            except err.OlmVerificationError as e:
                return (payload, e)

        if not is_prekey:
            await self._recover_from_undecryptable_olm(event)
            raise err.OlmExcpectedPrekey()

        try:
            session = olm.InboundSession(self._account, message, sender_curve)
            self._account.remove_one_time_keys(session)
            decrypted = session.decrypt(message)
        except olm.OlmSessionError as e:
            await self._recover_from_undecryptable_olm(event)
            raise err.OlmSessionError(code=e.args[0], was_new_session=True)

        self._sessions.setdefault(sender_curve, deque).append(session)
        await self.save()

        payload = json.loads(decrypted)  # TODO catch json error

        try:
            return (self._verify_olm_payload(event, payload), None)
        except err.OlmVerificationError as e:
            return (payload, e)


    async def _decrypt_megolm_payload(
        self, event: TimelineEvent[Megolm],
    ) -> Tuple[Payload, DeviceChain, List[err.MegolmVerificationError]]:

        room_id = event.room.id
        content = event.content
        key     = (room_id, content.sender_curve25519, content.session_id)

        try:
            session, starter_ed25519, decrypted_indice, forward_chain = \
                self._in_group_sessions[key]
        except KeyError:
            await self._request_group_session(event)
            raise err.NoInboundGroupSessionToDecrypt(*key)

        # Last device is our current one because this chain is to be sent
        # to users who might request this session
        forward_chain = forward_chain[:-1]

        device_chain, verrors = self._verify_megolm(
            event, content.sender_curve25519, starter_ed25519, forward_chain,
        )

        try:
            json_payload, message_index = session.decrypt(content.ciphertext)
        except olm.OlmGroupSessionError as e:
            await self._request_group_session(event)
            raise err.MegolmSessionError(code=e.args[0])

        known = message_index in decrypted_indice

        if known and decrypted_indice[message_index] != (event.id, event.date):
            raise err.PossibleReplayAttack()

        if not known and not event.local_echo:
            decrypted_indice[message_index] = (event.id, event.date)
            await self.save()

        # TODO: catch json error
        return (json.loads(json_payload), device_chain, verrors)


    async def _encrypt_room_event(
        self,
        room_id:   RoomId,
        for_users: Collection[UserId],
        settings:  Encryption,
        content:   EventContent,
    ) -> Megolm:

        for_users = set(for_users)

        self.client.debug("Encrypt {}/{} for {}", room_id, content, for_users)

        default: tuple = (olm.OutboundGroupSession(), datetime.utcnow(), 0, {})

        session, creation_date, encrypted_events_count, shared_to = \
            self._out_group_sessions.get(room_id, default)

        # If we have no existing non-expired OutbondGroupSession for this room:
        if (
            room_id not in self._out_group_sessions or
            datetime.utcnow() - creation_date > settings.sessions_max_age or
            encrypted_events_count > settings.sessions_max_messages
        ):
            key = (room_id, self.device.curve25519, session.id)
            self.client.debug(
                "Create matching in group session for new outbound: {}", key,
            )

            our_ed     = self.device.ed25519
            in_session = olm.InboundGroupSession(session.session_key)

            self._in_group_sessions[key] = (in_session, our_ed, {}, [])

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
        self.client.debug("Will encrypt payload: {}", payload)

        encrypted = Megolm(
            sender_curve25519 = self.device.curve25519,
            device_id         = self.client.device_id,
            session_id        = session.id,
            ciphertext        = session.encrypt(self._canonical_json(payload)),
        )

        self._out_group_sessions[room_id] = (
            session, creation_date, encrypted_events_count + 1, shared_to,
        )
        await self.save()

        return encrypted


    async def _decrypt_media(
        self, data: AsyncIterator[bytes], info: EncryptedMediaInfo,
    ) -> AsyncIterator[bytes]:

        try:
            wanted_sha256 = decode_base64(info.sha256)
            aes256_key    = decode_base64(info.key)
            init_vector   = decode_base64(info.init_vector)
        except BinAsciiError as e:
            raise err.MediaInvalidBase64(next(iter(e.args), ""))

        sha256     = SHA256.new()
        prefix     = init_vector[:8]
        init_value = int.from_bytes(init_vector[8:], "big")
        counter    = Counter.new(64, prefix=prefix, initial_value=init_value)

        try:
            cipher = AES.new(aes256_key, AES.MODE_CTR, counter=counter)
        except ValueError as e:
            raise err.MediaAESError(next(iter(e.args), ""))

        async for chunk in data:
            sha256.update(chunk)
            yield cipher.decrypt(chunk)

        got_sha256 = sha256.digest()

        if wanted_sha256 != got_sha256:
            raise err.MediaSHA256Mismatch(wanted_sha256, got_sha256)


    async def _encrypt_media(
        self, data: AsyncIterator[bytes],
    ) -> AsyncIterator[Union[bytes, EncryptedMediaInfo]]:

        aes256_key  = Random.new().read(32)
        init_vector = Random.new().read(8)
        counter     = Counter.new(64, prefix=init_vector, initial_value=0)
        cipher      = AES.new(aes256_key, AES.MODE_CTR, counter=counter)
        sha256      = SHA256.new()

        async for chunk in data:
            encrypted = cipher.encrypt(chunk)
            sha256.update(encrypted)
            yield encrypted

        yield EncryptedMediaInfo(
            mxc             = MXC("mxc://replace/me"),
            init_vector     = encode_base64(init_vector + b"\x00" * 8),
            key             = encode_base64(aes256_key, urlsafe=True),
            sha256          = encode_base64(sha256.digest()),
            key_operations  = ["encrypt", "decrypt"],
            key_type        = "oct",
            key_algorithm   = "A256CTR",
            key_extractable = True,
            version         = "v2",
        )


    async def _drop_outbound_group_session(self, room_id: RoomId) -> None:
        self.client.debug("Drop out group sessions for {}", room_id)
        self._out_group_sessions.pop(room_id, None)
        await self.save()


    async def _forward_group_session(
        self, to_user_id: UserId, request: GroupSessionRequest,
    ) -> None:

        client  = self.client
        devices = client.devices
        details = self._in_group_sessions.get(request.compare_key)

        if not details:
            client.info("Ignoring {}, no matching session to share", request)
            return

        dev = devices.get(to_user_id, {}).get(request.requesting_device_id)

        if not dev:
            client.warn("Ignoring {} from unknown device", request)
            return

        if dev.user_id != devices.client.user_id:
            client.warn("Ignoring {}, session not created by us", request)
            return

        if not dev.trusted:
            client.info(
                "Pending {} from untrusted device {}. A reply allowing this "
                "device to decrypt previous messages it has lost will be sent "
                "if you mark it as trusted.",
                request, dev,
            )
            dev.pending_session_requests[request.request_id] = request
            await devices.save()
            return

        session, creator_ed25519, _i, forward_chain = details

        exported = session.export_session(session.first_known_index)

        info = ForwardedGroupSessionInfo(
            algorithm                  = MegolmAlgorithm.megolm_v1,
            room_id                    = request.room_id,
            session_creator_curve25519 = request.session_creator_curve25519,
            creator_supposed_ed25519   = creator_ed25519,
            session_id                 = session.id,
            session_key                = exported,
            curve25519_forward_chain   = forward_chain,
        )

        client.info("Replying to {}'s {} with {}", to_user_id, request, info)

        olms, no_otks = await devices.encrypt(info, dev)

        if no_otks:
            client.warn("No one-time key for {}, can't send {}", no_otks, info)
            return

        task = ensure_future(devices.send(olms))  # type: ignore
        self._forward_tasks[request.request_id] = task
        await task

        if dev.pending_session_requests.pop(request.request_id, None):
            await devices.save()


    async def _cancel_forward_group_session(
        self, for_user_id: UserId, request: CancelGroupSessionRequest,
    ) -> None:

        self.client.debug("Applying {} from {}", request, for_user_id)

        devices = self.client.devices

        task = self._forward_tasks.pop(request.request_id, None)
        dev  = devices.get(for_user_id, {}).get(request.requesting_device_id)

        if task:
            task.cancel()

        if dev:
            dev.pending_session_requests.pop(request.request_id, None)


    # Internal methods that are only called from this module

    async def _upload_keys(self) -> None:
        device_keys = {
            "user_id":    self.client.user_id,
            "device_id":  self.client.device_id,
            "algorithms": [Algorithm.olm_v1.value, Algorithm.megolm_v1.value],
            "keys": {
                f"{kind}:{self.client.device_id}": key
                for kind, key in self._account.identity_keys.items()
            },
        }

        data     = {"device_keys": self._sign_dict(device_keys)}
        reply    = await self.net.post(self.net.api / "keys" / "upload", data)
        uploaded = reply.json["one_time_key_counts"].get("signed_curve25519")
        await self._upload_one_time_keys(uploaded or 0)


    async def _claim_one_time_keys(
        self, *devices: Device, timeout: float = 10,
    ) -> Dict[Device, str]:

        if not devices:
            return {}

        self.client.debug("Claiming keys for devices {}", devices)

        otk: Dict[str, Dict[str, str]] = {}
        for d in devices:
            otk.setdefault(d.user_id, {})[d.device_id] = "signed_curve25519"

        data  = {"timeout": int(timeout * 1000), "one_time_keys": otk}
        reply = await self.net.post(self.net.api / "keys" / "claim", data)

        if reply.json["failures"]:
            self.client.warn("Failed claiming: {}", reply.json["failures"])

        await self.client.devices.ensure_tracked(
            set(reply.json["one_time_keys"]),
        )

        valided: Dict[Device, str] = {}

        for user_id, device_keys in reply.json["one_time_keys"].items():
            for device_id, keys in device_keys.items():
                for key_dict in keys.copy().values():
                    dev = self.client.devices[user_id][device_id]

                    if "key" not in key_dict:
                        self.client.warn(
                            "No key for {} claim: {}", dev, key_dict,
                        )
                        continue

                    try:
                        self._verify_signed_dict(
                            key_dict, user_id, device_id, dev.ed25519,
                        )
                    except err.InvalidSignedDict as e:
                        self.client.warn(
                            "Rejected {} claimed key {}: {}", dev, key_dict, e,
                        )
                    else:
                        valided[dev] = key_dict["key"]

        return valided


    async def _recover_from_undecryptable_olm(
        self, event: ToDeviceEvent[Olm],
    ) -> bool:

        if event.sender in self._recovered_olm_this_sync:
            self.client.debug(
                "Already tried olm recovery with {} this sync", event.sender,
            )
            return False

        self._recovered_olm_this_sync.add(event.sender)

        self.client.info(
            "Olm session with {} has been corrupted, creating a replacement",
            event.sender,
        )

        devices = self.client.devices
        await devices.ensure_tracked([event.sender])
        device = devices.by_curve[event.content.sender_curve25519]

        olms, no_otks = await devices.encrypt(
            Dummy(), device, force_new_sessions=True,
        )

        if no_otks:
            self.client.warn(
                "Didn't get any one-time keys for {}, can't send new session!",
                no_otks,
            )
            return True

        await devices.send(olms)  # type: ignore

        for request, sent_to in self._sent_session_requests.values():
            if event.sender in sent_to:
                self.client.info(
                    "Assuming we have lost the response to {} sent by {}, "
                    "resending the request over fresh olm session",
                    request, event.sender,
                )
                await devices.send({device: request.cancellation})
                await devices.send({device: request})

        return True


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
            algorithm   = MegolmAlgorithm.megolm_v1,
            room_id     = room_id,
            session_id  = session.id,
            session_key = session.session_key,
        )

        self.client.debug("Sharing {} to {}", info, to)
        olms, no_otks = await self.client.devices.encrypt(info, *to)

        if no_otks:
            self.client.warn(
                "Didn't get any one-time keys for {}, they won't receive "
                "the keys to decrypt messages sent over group session {}!",
                no_otks, info,
            )

        await self.client.devices.send(olms)  # type: ignore


    async def _request_group_session(
        self, for_event: TimelineEvent[Megolm],
    ) -> None:

        curve       = for_event.content.sender_curve25519
        session_id  = for_event.content.session_id
        request_key = (for_event.room.id, curve, session_id)

        if request_key in self._sent_session_requests:
            return

        request = GroupSessionRequest.from_megolm(for_event)
        send_to = {self.client.user_id, for_event.sender}
        self.client.info(
            "Trying to recover some undecryptable events by sending {} to {}. "
            "They must trust your device or manually approve the request.",
            request, send_to,
        )

        self._sent_session_requests[request_key] = (request, send_to)

        await self.client.devices.ensure_tracked([for_event.sender])

        await self.client.devices.send({
            device: request
            for target in send_to
            for device in self.client.devices[target].values()
            if device.trusted is not False
        })

        await self.save()


    # Internal utils and verification tools only called from this module

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

        signature = self._account.sign(self._canonical_json(dct))
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


    def _verify_megolm(
        self,
        event:                    TimelineEvent[Megolm],
        sender_curve25519:        str,
        session_creator_ed25519:  str,
        curve25519_forward_chain: List[str],
    ) -> Tuple[DeviceChain, List[err.MegolmVerificationError]]:

        errors:       List[err.MegolmVerificationError] = []
        device_chain: DeviceChain                       = []

        content = event.content
        device  = self.client.devices.by_curve.get(content.sender_curve25519)

        if device and device.ed25519 == session_creator_ed25519:
            if device.trusted is False:
                errors.append(err.MegolmFromBlockedDevice(device))
            elif device.trusted is None:
                errors.append(err.MegolmFromUntrustedDevice(device))
        else:
            args = (session_creator_ed25519, content.sender_curve25519)
            errors.append(err.MegolmWrongSender(*args))

        for curve in curve25519_forward_chain:
            found = self.client.devices.by_curve.get(curve)
            device_chain.append(found or curve)

            if found and found.trusted is False:
                errors.append(err.MegolmBlockedDeviceInForwardChain(found))
            elif not found or found.trusted is None:
                errors.append(err.MegolmUntrustedDeviceInForwardChain(found))

        return (device_chain, errors)


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
