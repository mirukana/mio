# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from asyncio import Lock
from contextlib import suppress
from dataclasses import dataclass, field
from typing import (
    TYPE_CHECKING, Any, Collection, DefaultDict, Deque, Dict, List, Optional,
    Set, Tuple,
)
from uuid import uuid4

import olm
from aiopath import AsyncPath

from ..core.callbacks import CallbackGroup, Callbacks, EventCallbacks
from ..core.contents import EventContent
from ..core.data import IndexableMap, Parent, Runtime
from ..core.ids import InvalidId, UserId
from ..core.utils import DictS
from ..e2e.contents import (
    CancelGroupSessionRequest, ForwardedGroupSessionInfo, GroupSessionInfo,
    GroupSessionRequest, Olm,
)
from ..e2e.errors import InvalidSignedDict
from ..module import JSONClientModule
from . import errors
from .device import Device
from .events import ToDeviceEvent

if TYPE_CHECKING:
    from ..client import Client

# {user_id: [device_id]} - empty list means to get all devices for that user
UserDeviceIds = Dict[UserId, List[str]]

DeviceMap = IndexableMap[UserId, Dict[str, Device]]


@dataclass
class MioDeviceCallbacks(CallbackGroup):
    async def on_megolm_keys(
        self, devices: "Devices", event: ToDeviceEvent[GroupSessionInfo],
    ) -> None:

        assert event.decryption
        assert event.decryption.payload
        assert isinstance(event.decryption.original.content, Olm)

        sender_curve25519 = event.decryption.original.content.sender_curve25519
        sender_ed25519    = event.decryption.payload["keys"]["ed25519"]
        content           = event.content

        ses = devices.client.e2e._in_group_sessions
        key = (content.room_id, sender_curve25519, content.session_id)

        if key not in ses:
            session  = olm.InboundGroupSession(content.session_key)
            ses[key] = (session, sender_ed25519, {}, [])
            devices.client.debug("Added group session from {}", event)

            devices.client.e2e._sent_session_requests.pop(key, None)
            await devices.client.e2e.save()

            if content.room_id in devices.client.rooms:
                timeline = devices.client.rooms[content.room_id].timeline
                await timeline._retry_decrypt(key[1:])


    async def on_forwarded_megolm_keys(
        self,
        devices: "Devices",
        event:   ToDeviceEvent[ForwardedGroupSessionInfo],
    ) -> None:

        client           = devices.client
        content          = event.content
        requests         = client.e2e._sent_session_requests
        request, sent_to = requests.get(content.compare_key, (None, {}))

        if not request or not sent_to:
            client.warn("Ignoring unrequested {} ({})", event, set(requests))
            return

        if not event.decryption:
            client.warn("Ignoring {} sent unencrypted", event)
            return

        try:
            key     = content.session_key
            session = olm.InboundGroupSession.import_session(key)
        except olm.OlmGroupSessionError:
            client.exception("Failed importing session from {}", event)
            return

        if content.compare_key in client.e2e._in_group_sessions:
            client.warn("Session already present for {}, ignoring", event)
            return

        sender_curve = event.decryption.original.content.sender_curve25519

        client.e2e._in_group_sessions[content.compare_key] = (
            session,
            content.creator_supposed_ed25519,
            {},
            content.curve25519_forward_chain + [sender_curve],
        )
        client.debug("Imported group session from {}", event)

        requests.pop(content.compare_key)
        await client.e2e.save()
        await client.rooms._retry_decrypt(content.compare_key)

        await devices.send({
            device: request.cancellation
            for user_id in sent_to
            for device in devices[user_id].values()
        })


    async def on_megolm_keys_request(
        self,
        devices: "Devices",
        event:   ToDeviceEvent[GroupSessionRequest],
    ) -> None:

        e2e = devices.client.e2e
        await e2e._forward_group_session(event.sender, event.content)


    async def on_megolm_keys_request_cancel(
        self,
        devices: "Devices",
        event:   ToDeviceEvent[CancelGroupSessionRequest],
    ) -> None:

        e2e = devices.client.e2e
        await e2e._cancel_forward_group_session(event.sender, event.content)


@dataclass
class Devices(JSONClientModule, DeviceMap, EventCallbacks):
    client: Parent["Client"] = field(repr=False)

    # {user_id: {device_id: Device}}
    _data: Dict[UserId, Dict[str, Device]] = field(default_factory=dict)

    by_curve: Runtime[Dict[str, Device]] = field(default_factory=dict)

    # {user_id: sync.next_batch of last change of None for full update}
    outdated: Dict[UserId, Optional[str]] = field(default_factory=dict)

    callbacks: Runtime[Callbacks] = field(
        init=False, repr=False, default_factory=lambda: DefaultDict(list),
    )

    callback_groups: Runtime[List[CallbackGroup]] = field(
        init=False, repr=False, default_factory=lambda: [MioDeviceCallbacks()],
    )

    _query_lock: Runtime[Lock] = field(init=False, default_factory=Lock)


    @property
    def path(self) -> AsyncPath:
        return self.client.path.parent / "devices.json"


    @property
    def own(self) -> Dict[str, Device]:
        return self[self.client.user_id]


    @property
    def current(self) -> Device:
        return self.own[self.client.device_id]


    async def delete(self, auth: DictS, *devices_id: str) -> None:
        """Delete own devices from the server using an authentication dict."""

        body = {"devices": devices_id, "auth": auth}
        await self.net.post(self.net.api / "delete_devices", body)

        if any(i == self.current.device_id for i in devices_id):
            del self.own[self.client.device_id]
            await self.save()

            self.client.access_token = ""
            await self.client.save()
            await self.client.terminate()
        else:
            await self.update([self.client.user_id])


    async def delete_password(self, password: str, *devices_id: str) -> None:
        """Delete own devices from the server using password authentication."""

        await self.delete({
            "type":     "m.login.password",
            "user":     self.client.user_id,
            "password": password,
        }, *devices_id)


    async def ensure_tracked(
        self, users: Collection[UserId], timeout: float = 10,
    ) -> None:

        self.client.debug("Ensure tracking for {}", users)

        for devices in self.values():
            for device in devices.values():
                self.by_curve[device.curve25519] = device

        await self.update({u for u in users if u not in self}, timeout=timeout)


    async def update(
        self,
        users:      Collection[UserId],
        sync_token: Optional[str] = None,
        timeout:    float         = 10,
    ) -> None:

        self.outdated.update({u: sync_token for u in users})

        if not self.outdated:
            return

        await self.save()

        async with self._query_lock:
            self.client.debug("Updating devices for {}", set(self.outdated))

            reply = await self.net.post(
                self.net.api / "keys" / "query",
                {
                    # [] means "get all devices of the user" to the server
                    "device_keys": {user_id: [] for user_id in self.outdated},
                    "token":       sync_token,
                    "timeout":     int(timeout * 1000),
                },
            )

            if reply.json["failures"]:
                self.client.warn(
                    "Failed querying devices of some users for {}: {}",
                    set(self.outdated),
                    reply.json["failures"],
                )

            for user_id, queried_devices in reply.json["device_keys"].items():
                with self.client.report(InvalidId) as caught:
                    user_id = UserId(user_id)

                if caught:
                    continue

                if self.outdated[user_id] == sync_token:
                    del self.outdated[user_id]

                for device_id, device in self.get(user_id, {}).copy().items():
                    if device_id not in queried_devices:
                        del self[user_id][device_id]
                        del self.by_curve[device.curve25519]

                for device_id, info in queried_devices.items():
                    try:
                        added = self._handle_queried(user_id, device_id, info)
                        self.client.debug("Registered {}", added)
                    except (errors.QueriedDeviceError, InvalidSignedDict) as e:
                        self.client.warn(
                            "Rejected queried device {}: {}", info, e,
                        )

            await self.save()


    def drop(self, *users: UserId) -> None:
        self.client.debug("Dropping devices of users {}", users)

        for user_id in users:
            for device in self._data.pop(user_id, {}).values():
                self.by_curve.pop(device.curve25519, None)


    async def encrypt(
        self,
        content:            EventContent,
        *devices:           Device,
        force_new_sessions: bool = False,
    ) -> Tuple[Dict[Device, Olm], Set[Device]]:

        sessions:        Dict[Device, olm.Session] = {}
        no_session_devs: Set[Device]               = set()
        olms:            Dict[Device, Olm]         = {}
        no_otks:         Set[Device]               = set()

        e2e = self.client.e2e

        for device in devices:
            if force_new_sessions:
                no_session_devs.add(device)
                continue

            try:
                sessions[device] = e2e._sessions[device.curve25519][-1]
            except (KeyError, IndexError):
                no_session_devs.add(device)

        new_otks = await e2e._claim_one_time_keys(*no_session_devs)

        for device in no_session_devs:
            if device not in new_otks:
                no_otks.add(device)
            else:
                sessions[device] = olm.OutboundSession(
                    e2e._account, device.curve25519, new_otks[device],
                )
                d: Deque       = Deque(maxlen=e2e._max_sessions_per_device)
                saved_sessions = e2e._sessions.setdefault(device.curve25519, d)
                saved_sessions.append(sessions[device])

        payload_base: Dict[str, Any] = {
            "type":    content.type,
            "content": content.dict,
            "sender":  self.client.user_id,
            "keys":    {"ed25519": self.current.ed25519},
        }

        for device, session in sessions.items():
            payload = {
                **payload_base,
                "recipient":      device.user_id,
                "recipient_keys": {"ed25519": device.ed25519},
            }

            self.client.debug("Encrypting {} for {}", payload, device)
            msg    = session.encrypt(e2e._canonical_json(payload))
            cipher = Olm.Cipher(type=msg.message_type, body=msg.ciphertext)

            olms[device] = Olm(
                sender_curve25519 = self.current.curve25519,
                ciphertext        = {device.curve25519: cipher},
            )

        await self.save()
        return (olms, no_otks)


    async def send(self, contents: Dict[Device, EventContent]) -> None:
        m_type = next(iter(contents.values()), EventContent()).type
        assert m_type

        if not all(c.type == m_type for c in contents.values()):
            raise TypeError(f"Not all contents have the same type: {contents}")

        # We don't want to send events to the device we're using right now
        contents.pop(self.current, None)

        if not contents:
            return

        await self.ensure_tracked({device.user_id for device in contents})

        msgs: Dict[UserId, Dict[str, Dict[str, Any]]] = {}

        for device, content in contents.items():
            key1 = device.user_id
            msgs.setdefault(key1, {})[device.device_id] = content.dict

        # When all devices of an user are given with the same event,
        # compress the whole device dict into {"*": event}
        for user_id, devices in msgs.items():
            all_devices   = set(self[user_id]) <= set(devices)
            device_events = list(devices.values())
            same_events   = all(e == device_events[0] for e in device_events)

            if all_devices and same_events:
                msgs[user_id] = {"*": device_events[0]}

        await self.net.put(
            self.net.api / "sendToDevice" / m_type / str(uuid4()),
            {"messages": msgs},
        )


    def _handle_queried(
        self, user_id: UserId, device_id: str, info: Dict[str, Any],
    ) -> Device:

        if info["user_id"] != user_id:
            raise errors.DeviceUserIdMismatch(user_id, info["user_id"])

        if info["device_id"] != device_id:
            raise errors.DeviceIdMismatch(device_id, info["device_id"])

        signer_ed25519 = info["keys"][f"ed25519:{device_id}"]
        verify         = self.client.e2e._verify_signed_dict
        verify(info, user_id, device_id, signer_ed25519)

        with suppress(KeyError):
            ed25519 = self[user_id][device_id].ed25519
            if ed25519 != signer_ed25519:
                raise errors.DeviceEd25519Mismatch(ed25519, signer_ed25519)

        present    = self._data.get(user_id, {}).get(device_id)
        us         = self.client
        own_device = user_id == us.user_id and device_id == us.device_id

        device = Device(
            devices        = self,
            user_id        = user_id,
            device_id      = device_id,
            ed25519        = signer_ed25519,
            curve25519     = info["keys"][f"curve25519:{device_id}"],
            e2e_algorithms = info["algorithms"],

            trusted =
                True if own_device else present.trusted if present else None,

            display_name =
                info.get("unsigned", {}).get("device_display_name"),
        )

        self._data.setdefault(user_id, {})[device_id] = device
        self.by_curve[device.curve25519]              = device
        return device
