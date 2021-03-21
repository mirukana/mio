import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional

from ..core.data import JSON, Parent
from ..core.types import UserId
from ..e2e.contents import GroupSessionRequest

if TYPE_CHECKING:
    from .devices import Devices


@dataclass(unsafe_hash=True)
class Device(JSON):
    devices:        Parent["Devices"] = field(repr=False, compare=False)
    user_id:        UserId
    device_id:      str
    ed25519:        str            = field(compare=False)
    curve25519:     str            = field(compare=False)
    e2e_algorithms: List[str]      = field(compare=False)
    display_name:   Optional[str]  = field(default=None, compare=False)
    trusted:        Optional[bool] = field(default=None, compare=False)

    pending_session_requests: Dict[str, GroupSessionRequest] = field(
        default_factory=dict, compare=False,
    )


    async def trust(self) -> None:
        self.trusted = True
        await self.devices.save()

        forward = self.devices.client.e2e.forward_group_session

        await asyncio.gather(*[
            forward(self.user_id, request)
            for request in self.pending_session_requests.values()
        ])


    async def block(self) -> None:
        self.trusted = False

        e2e      = self.devices.client.e2e
        sessions = e2e.out_group_sessions

        for room_id, (_s, _c, _e, shared_to) in sessions.copy().items():
            if self.device_id in shared_to.get(self.user_id, set()):
                await e2e.drop_outbound_group_session(room_id)

        await self.devices.save()
