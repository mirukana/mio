from asyncio import Lock
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    TYPE_CHECKING, Any, Collection, DefaultDict, Dict, List, Optional, Set,
    Tuple,
)
from uuid import uuid4

import olm

from ..core.callbacks import CallbackGroup, Callbacks, EventCallbacks
from ..core.contents import EventContent
from ..core.data import IndexableMap, Parent, Runtime
from ..core.types import UserId
from ..core.utils import get_logger
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

LOG = get_logger()

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

        ses = devices.client._e2e.in_group_sessions
        key = (content.room_id, sender_curve25519, content.session_id)

        if key not in ses:
            session  = olm.InboundGroupSession(content.session_key)
            ses[key] = (session, sender_ed25519, {}, [])
            LOG.info("Added group session from %r", event)

            devices.client._e2e.sent_session_requests.pop(key, None)
            await devices.client._e2e.save()

            if content.room_id in devices.client.rooms:
                timeline = devices.client.rooms[content.room_id].timeline
                await timeline._retry_decrypt(key[1:])


    async def on_forwarded_megolm_keys(
        self,
        devices: "Devices",
        event:   ToDeviceEvent[ForwardedGroupSessionInfo],
    ) -> None:

        content          = event.content
        requests         = devices.client._e2e.sent_session_requests
        request, sent_to = requests.get(content.compare_key, (None, {}))

        if not request or not sent_to:
            LOG.warning("Ignoring unrequested %r (%r)", event, set(requests))
            return

        if not event.decryption:
            LOG.warning("Ignoring %r sent unencrypted", event)
            return

        try:
            key     = content.session_key
            session = olm.InboundGroupSession.import_session(key)
        except olm.OlmGroupSessionError:
            LOG.exception("Failed importing session from %r", event)
            return

        if content.compare_key in devices.client._e2e.in_group_sessions:
            LOG.warning("Session already present for %r, ignoring", event)
            return

        sender_curve = event.decryption.original.content.sender_curve25519

        devices.client._e2e.in_group_sessions[content.compare_key] = (
            session,
            content.creator_supposed_ed25519,
            {},
            content.curve25519_forward_chain + [sender_curve],
        )
        LOG.info("Imported group session from %r", event)

        requests.pop(content.compare_key)
        await devices.client._e2e.save()

        if content.room_id in devices.client.rooms:
            timeline = devices.client.rooms[content.room_id].timeline
            await timeline._retry_decrypt(content.compare_key[1:])

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

        e2e = devices.client._e2e
        await e2e.forward_group_session(event.sender, event.content)


    async def on_megolm_keys_request_cancel(
        self,
        devices: "Devices",
        event:   ToDeviceEvent[CancelGroupSessionRequest],
    ) -> None:

        e2e = devices.client._e2e
        await e2e.cancel_forward_group_session(event.sender, event.content)


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

    callback_groups: Runtime[List["CallbackGroup"]] = field(
        init=False, repr=False, default_factory=lambda: [MioDeviceCallbacks()],
    )

    _query_lock: Runtime[Lock] = field(init=False, default_factory=Lock)


    @property
    def path(self) -> Path:
        return self.client.path.parent / "devices.json"


    @property
    def own(self) -> Dict[str, Device]:
        return self[self.client.user_id]


    @property
    def current(self) -> Device:
        return self.own[self.client.device_id]


    async def ensure_tracked(
        self, users: Collection[UserId], timeout: float = 10,
    ) -> None:

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
            LOG.info("Querying devices for %r", set(self.outdated))

            result = await self.client.send_json(
                "POST",
                self.client.api / "keys" / "query",
                {
                    # [] means "get all devices of the user" to the server
                    "device_keys": {user_id: [] for user_id in self.outdated},
                    "token":       sync_token,
                    "timeout":     int(timeout * 1000),
                },
            )

            if result["failures"]:
                LOG.warning(
                    "Failed querying devices of some users for %r: %r",
                    set(self.outdated),
                    result["failures"],
                )

            for user_id, queried_devices in result["device_keys"].items():
                user_id = UserId(user_id)

                if self.outdated[user_id] == sync_token:
                    del self.outdated[user_id]

                for device_id, device in self.get(user_id, {}).copy().items():
                    if device_id not in queried_devices:
                        del self[user_id][device_id]
                        del self.by_curve[device.curve25519]

                for device_id, info in queried_devices.items():
                    try:
                        added = self._handle_queried(user_id, device_id, info)
                        LOG.info("Registered %r", added)
                    except (errors.QueriedDeviceError, InvalidSignedDict) as e:
                        LOG.warning("Rejected queried device %r: %r", info, e)

            await self.save()


    def drop(self, *users: UserId) -> None:
        for user_id in users:
            for device in self._data.pop(user_id, {}).values():
                self.by_curve.pop(device.curve25519, None)


    async def send(self, contents: Dict[Device, EventContent]) -> None:
        m_type = next(iter(contents.values()), EventContent()).type
        assert m_type

        if not all(c.type == m_type for c in contents.values()):
            raise TypeError(f"Not all contents have the same type: {contents}")

        # We don't want to send events to the device we're using right now
        contents.pop(self.current, None)

        if not contents:
            return

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

        await self.client.send_json(
            "PUT",
            self.client.api / "sendToDevice" / m_type / str(uuid4()),
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
        verify         = self.client._e2e._verify_signed_dict
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


    async def _encrypt(
        self, content: EventContent, *devices: Device,
    ) -> Tuple[Dict[Device, Olm], Set[Device]]:

        sessions:         Dict[Device, olm.Session] = {}
        missing_sessions: Set[Device]               = set()
        olms:             Dict[Device, Olm]         = {}
        no_otks:          Set[Device]               = set()

        e2e = self.client._e2e

        for device in devices:
            try:
                sessions[device] = sorted(
                    e2e.sessions[device.curve25519],
                    key=lambda session: session.id,
                )[0]
            except (KeyError, IndexError):
                missing_sessions.add(device)

        new_otks = await e2e._claim_one_time_keys(*missing_sessions)

        for device in missing_sessions:
            if device not in new_otks:
                no_otks.add(device)
            else:
                sessions[device] = olm.OutboundSession(
                    e2e.account, device.curve25519, new_otks[device],
                )
                e2e.sessions.setdefault(
                    device.curve25519, [],
                ).append(sessions[device])

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

            msg    = session.encrypt(e2e._canonical_json(payload))
            cipher = Olm.Cipher(type=msg.message_type, body=msg.ciphertext)

            olms[device] = Olm(
                sender_curve25519 = self.current.curve25519,
                ciphertext        = {device.curve25519: cipher},
            )

        await self.save()
        return (olms, no_otks)
