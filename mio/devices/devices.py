from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple
from uuid import uuid4

import olm

from ..core.contents import EventContent
from ..core.data import IndexableMap
from ..core.types import UserId
from ..core.utils import get_logger
from ..e2e.contents import Olm, RoomKey
from ..e2e.errors import InvalidSignedDict
from ..module import JSONClientModule
from . import errors
from .device import Device
from .events import ToDeviceEvent

if TYPE_CHECKING:
    from ..client import Client

LOG = get_logger()


@dataclass
class Devices(JSONClientModule, IndexableMap[UserId, Dict[str, Device]]):
    _data: Dict[UserId, Dict[str, Device]] = field(default_factory=dict)


    async def __ainit__(self) -> None:
        if self.client.user_id not in self:
            await self.query({self.client.user_id: []})
            await self.save()


    @property
    def own(self) -> Dict[str, Device]:
        return self[self.client.user_id]


    @property
    def current(self) -> Device:
        return self.own[self.client.device_id]


    @classmethod
    def get_path(cls, parent: "Client", **kwargs) -> Path:
        return parent.path.parent / "devices.json"


    async def query(
        self,
        # {user_id: [device_id]} - empty list = all devices for that user
        devices:      Dict[UserId, List[str]],
        update_token: Optional[str] = None,
        timeout:      float         = 10,
    ) -> None:

        if not update_token and any(d != [] for d in devices.values()):
            raise ValueError("No update_token to do partial device queries")

        if not update_token:
            devices = {u: d for u, d in devices.items() if u not in self}

        if not devices:
            return

        LOG.info("Querying devices: %r", devices)

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
            LOG.warning("Failed querying some devices: %s", result["failures"])

        for user_id, devs in result["device_keys"].items():
            for device_id, info in devs.items():
                try:
                    self._handle_queried_device(user_id, device_id, info)
                except (errors.QueriedDeviceError, InvalidSignedDict) as e:
                    LOG.warning("Rejected queried device %r: %r", info, e)

        await self.save()


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
            method = "PUT",
            path   = [*self.client.api, "sendToDevice", m_type, str(uuid4())],
            body   = {"messages": msgs},
        )


    async def handle_event(self, event: ToDeviceEvent) -> None:
        LOG.debug("%s got to-device event: %r", self.client.user_id, event)

        if not isinstance(event.content, RoomKey):
            return

        assert event.decryption
        assert isinstance(event.decryption.original.content, Olm)

        sender_curve25519 = event.decryption.original.content.sender_curve25519
        sender_ed25519    = event.decryption.payload["keys"]["ed25519"]
        content           = event.content

        ses = self.client.e2e.in_group_sessions
        key = (content.room_id, sender_curve25519, content.session_id)

        if key not in ses:
            session  = olm.InboundGroupSession(content.session_key)
            ses[key] = (session, sender_ed25519, {})
            await self.save()


    def _handle_queried_device(
        self, user_id: UserId, device_id: str, info: Dict[str, Any],
    ) -> None:

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

        self._data.setdefault(user_id, {})[device_id] = Device(
            user_id        = user_id,
            device_id      = device_id,
            ed25519        = signer_ed25519,
            curve25519     = info["keys"][f"curve25519:{device_id}"],
            e2e_algorithms = info["algorithms"],
            display_name   =
                info.get("unsigned", {}).get("device_display_name"),
        )


    async def _encrypt(
        self, content: EventContent, *devices: Device,
    ) -> Tuple[Dict[Device, Olm], Set[Device]]:

        sessions:         Dict[Device, olm.OutboundSession] = {}
        missing_sessions: Set[Device]                       = set()
        olms:             Dict[Device, Olm]                 = {}
        no_otks:          Set[Device]                       = set()

        e2e = self.client.e2e

        for device in devices:
            try:
                sessions[device] = sorted(
                    e2e.out_sessions[device.curve25519],
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
                e2e.out_sessions.setdefault(
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
