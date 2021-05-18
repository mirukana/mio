# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

import asyncio
import json
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from typing import (
    TYPE_CHECKING, Any, Callable, Dict, Iterator, List, Optional, Set, Type,
    Union,
)

from aiopath import AsyncPath

from .account_data.events import AccountDataEvent
from .core.data import Parent, Runtime
from .core.events import Event, InvalidEvent
from .core.ids import InvalidId, RoomId, UserId
from .core.utils import remove_none
from .devices.events import ToDeviceEvent
from .e2e.contents import Megolm, Olm
from .module import JSONClientModule
from .rooms.contents.users import Member
from .rooms.events import (
    EphemeralEvent, InvitedRoomStateEvent, StateBase, StateEvent,
    TimelineEvent,
)
from .rooms.room import Room

if TYPE_CHECKING:
    from .client import Client

FilterType = Union[None, str, Dict[str, Any]]


@dataclass
class Sync(JSONClientModule):
    client:     Parent["Client"] = field(repr=False)
    next_batch: Optional[str]    = None
    paused:     Runtime[bool]    = False


    @property
    def path(self) -> AsyncPath:
        return self.client.path.parent / "sync.json"


    async def once(
        self,
        timeout:      float          = 0,
        sync_filter:  FilterType     = None,
        since:        Optional[str]  = None,
        full_state:   Optional[bool] = None,
        set_presence: Optional[str]  = None,
        _handle:      bool           = True,
    ) -> Optional[dict]:

        filter_param: Any = None

        if sync_filter:
            filter_param = json.dumps(sync_filter, ensure_ascii=False)

        reply = await self.net.get(self.net.api / "sync" % remove_none({
            "timeout":      int(timeout * 1000),
            "filter":       filter_param,
            "since":        since or self.next_batch,
            "full_state":   full_state,
            "set_presence": set_presence,
            # or self.client.presence.to_set TODO
        }))

        if self.next_batch != reply.json["next_batch"]:
            if _handle:
                await self._handle_sync(reply.json)

            return reply.json

        return None


    async def loop(
        self,
        timeout:             float                      = 10,
        sync_filter:         FilterType                 = None,
        first_sync_filter:   FilterType                 = None,
        since:               Optional[str]              = None,
        full_state:          Optional[bool]             = None,
        set_presence:        Optional[str]              = None,
        sleep_between_syncs: float                      = 0.5,
    ) -> None:

        first_run = True

        while True:
            use_filter = first_sync_filter if first_run else sync_filter
            await self.once(timeout, use_filter, None, None, set_presence)
            first_run = False
            await asyncio.sleep(sleep_between_syncs)


    @contextmanager
    def pause(self) -> Iterator[None]:
        self.paused = True
        try:
            yield
        finally:
            self.paused = False


    async def _handle_sync(self, sync: Dict[str, Any]) -> None:
        # TODO: room account data, presence, refactor because it's way too long

        while self.paused:
            await asyncio.sleep(0.1)

        state_member_events: List[StateEvent[Member]] = []

        async def events_call(
            data: dict, key: str, evtype: Type[Event], coro: Callable,
        ) -> None:

            for event in data.get(key, {}).get("events", ()):
                with self.client.report(InvalidEvent):
                    ev = evtype.from_dict(event, self.client)

                    if isinstance(ev, ToDeviceEvent):
                        ev = await ev._decrypted()

                    await coro(ev)

        async def room_events_call(
            data: dict, key: str, room: Room, invited: bool = False,
        ) -> None:

            state: Type[StateBase] = \
                InvitedRoomStateEvent if invited else StateEvent

            for event in data.get(key, {}).get("events", ()):
                with self.client.report(InvalidEvent):
                    if "state_key" in event:
                        state_ev = state.from_dict(event, room)
                        await room.state._register(state_ev)

                        if isinstance(state_ev.content, Member):
                            state_member_events.append(state_ev)  # type:ignore

                    if key == "ephemeral":
                        await room._call_callbacks(
                            EphemeralEvent.from_dict(event, room),
                        )
                        continue

                    if key != "timeline":
                        continue

                    ev: TimelineEvent
                    ev = TimelineEvent.from_dict(event, room)
                    ev = await ev._decrypted()

                    await room.timeline._register_events(ev)

        # Global account data

        accdata_call = self.client.account_data._register
        await events_call(sync, "account_data", AccountDataEvent, accdata_call)

        # Devices

        e2e_senders: Set[UserId] = set()

        for event in sync.get("to_device", {}).get("events", ()):
            if Olm.matches(event):
                with suppress(InvalidEvent):
                    with self.client.report(InvalidId):
                        e2e_senders.add(UserId(event["sender"]))

        for kind in ("invite", "join"):
            for data in sync.get("rooms", {}).get(kind, {}).values():
                for event in data.get("timeline", {}).get("events", ()):
                    if Megolm.matches(event):
                        with suppress(InvalidEvent):
                            with self.client.report(InvalidId):
                                e2e_senders.add(UserId(event["sender"]))

        await self.client.devices.ensure_tracked(e2e_senders)

        changed = set()

        for user_id in sync.get("device_lists", {}).get("changed", []):
            with self.client.report(InvalidId):
                changed.add(UserId(user_id))

        await self.client.devices.update(changed)

        dev_call = self.client.devices._call_callbacks
        await events_call(sync, "to_device", ToDeviceEvent, dev_call)

        # Rooms

        rooms = self.client.rooms

        async def set_room(room_id: RoomId) -> Room:
            if room_id in rooms._data:
                return rooms._data[room_id]

            rooms._data[room_id] = Room(client=self.client, id=room_id)
            return rooms._data[room_id]

        # -- Invited rooms

        for room_id, data in sync.get("rooms", {}).get("invite", {}).items():
            with self.client.report(InvalidId) as caught:
                room = await set_room(RoomId(room_id))

            if not caught:
                room.invited = True
                room.left    = False
                await room_events_call(data, "invite_state", room)

        # -- Joined rooms

        for room_id, data in sync.get("rooms", {}).get("join", {}).items():
            with self.client.report(InvalidEvent) as caught:
                room = await set_room(RoomId(room_id))

            if caught:
                continue

            # TODO: save when changing invited/left
            room.invited = False
            room.left    = False

            summary = data.get("summary", {})
            unread  = data.get("unread_notifications", {})

            if summary.get("m.heroes"):
                room._lazy_load_heroes = tuple(summary["m.heroes"])

            if summary.get("m.joined_members_count"):
                room._lazy_load_joined = summary["m.joined_members_count"]

            if summary.get("m.invited_members_count"):
                room._lazy_load_joined = summary["m.invited_members_count"]

            if unread.get("notification_count"):
                room.unread_notifications = unread["notification_count"]

            if unread.get("highlight_count"):
                room.unread_highlights = unread["highlight_count"]

            timeline   = data.get("timeline", {})
            limited    = timeline.get("limited")
            prev_batch = timeline.get("prev_batch")

            after: Optional[TimelineEvent] = None

            for event in timeline.get("events", []):
                with suppress(InvalidEvent):
                    after = TimelineEvent.from_dict(event, room)
                    after = await after._decrypted(log=False)
                    break

            if limited and prev_batch and after:
                if not room.timeline:
                    await room.timeline.load_history(count=1)

                before_id = next(reversed(tuple(room.timeline)), None)
                await room.timeline._register_gap(
                    prev_batch, before_id, after.id, after.date,
                )

            await room_events_call(data, "state", room)
            await room_events_call(data, "timeline", room)
            await room_events_call(data, "ephemeral", room)

        # -- Left rooms

        for room_id, data in sync.get("rooms", {}).get("leave", {}).items():
            if room_id in self.client.rooms.forgotten:
                continue

            with self.client.report(InvalidId) as caught:
                room = await set_room(RoomId(room_id))

            if not caught:
                room.left = True
                # await events_call(data, "account_data", room.handle_event)
                await room_events_call(data, "state", room)
                await room_events_call(data, "timeline", room)

        # Left devices

        no_more_shared_e2e_room = set()

        for user_id in sync.get("device_lists", {}).get("left", []):
            with self.client.report(InvalidId):
                no_more_shared_e2e_room.add(user_id)

        self.client.devices.drop(*no_more_shared_e2e_room)

        # E2E one time keys

        if "device_one_time_keys_count" in sync:
            up = sync["device_one_time_keys_count"].get("signed_curve25519", 0)
            await self.client.e2e._upload_one_time_keys(currently_uploaded=up)

        # Profile

        await self.client.profile._update_on_sync(*state_member_events)

        # Finish

        self.next_batch = sync["next_batch"]
        await self.save()
