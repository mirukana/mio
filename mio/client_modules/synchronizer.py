import asyncio
import logging as log
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Set, Type, Union

from ..events import (
    Event, InvalidEvent, InvitedRoomStateEvent, StateEvent, StateKind,
    TimelineEvent, ToDeviceEvent,
)
from ..typing import RoomId, UserId
from ..utils import log_errors, remove_none
from .client_module import JSONClientModule
from .encryption.errors import DecryptionError
from .encryption.events import Megolm, Olm
from .rooms.room import Room

FilterType = Union[None, str, Dict[str, Any]]


@dataclass
class Synchronization(JSONClientModule):
    next_batch: Optional[str] = None

    async def sync(
        self,
        timeout:      float          = 0,
        sync_filter:  FilterType     = None,
        since:        Optional[str]  = None,
        full_state:   Optional[bool] = None,
        set_presence: Optional[str]  = None,
    ) -> None:

        parameters = {
            "timeout":      int(timeout * 1000),
            "filter":       sync_filter,
            "since":        since or self.next_batch,
            "full_state":   full_state,
            "set_presence": set_presence,
            # or self.client.presence.to_set TODO
        }

        # TODO: timeout
        result = await self.client.send_json(
            method     = "GET",
            path       = [*self.client.api, "sync"],
            parameters = remove_none(parameters),
        )

        if self.next_batch != result["next_batch"]:
            await self.handle_sync(result)


    async def loop(
        self,
        timeout:                     float          = 10,
        sync_filter:                 FilterType     = None,
        first_sync_filter:           FilterType     = None,
        since:                       Optional[str]  = None,
        full_state:                  Optional[bool] = None,
        set_presence:                Optional[str]  = None,
        sleep_seconds_between_syncs: float          = 1,
    ) -> None:

        await self.sync(0, first_sync_filter, since, full_state, set_presence)

        while True:
            await self.sync(timeout, sync_filter, None, None, set_presence)
            await asyncio.sleep(sleep_seconds_between_syncs)


    async def handle_sync(self, sync: Dict[str, Any]) -> None:
        # TODO: device_lists, partial syncs

        async def decrypt(event: Event, room_id: RoomId):
            if not isinstance(event, (ToDeviceEvent, TimelineEvent)):
                return event

            if not isinstance(event.content, (Olm, Megolm)):
                return event

            try:
                return await self.client.e2e.decrypt_event(event, room_id)
            except DecryptionError as e:
                log.warn("Failed decrypting %r: %r\n", event, e)
                return event

        async def events_call(
            data: dict, key: str, evtype: Type[Event], coro: Callable,
        ) -> None:
            for event in data.get(key, {}).get("events", ()):
                with log_errors(InvalidEvent):
                    ev = await decrypt(evtype.from_dict(event), room.id)
                    await coro(ev)

        async def room_events_call(
            data: dict, key: str, room: Room, invited: bool = False,
        ) -> None:

            state: Type[StateKind] = \
                InvitedRoomStateEvent if invited else StateEvent

            for event in data.get(key, {}).get("events", ()):
                with log_errors(InvalidEvent):
                    if "state_key" in event:
                        st = await decrypt(state.from_dict(event), room.id)
                        await room.handle_event(st)

                    if key != "timeline":
                        continue

                    ev = await decrypt(TimelineEvent.from_dict(event), room.id)
                    await room.handle_event(ev)

        users: Set[UserId] = set()

        for event in sync.get("to_device", {}).get("events", ()):
            if Olm.matches(event):
                with suppress(InvalidEvent):
                    users.add(ToDeviceEvent.from_dict(event).sender)

        for kind in ("invite", "join", "leave"):
            for data in sync.get("rooms", {}).get(kind, {}).values():
                for event in data.get("timeline", {}).get("events", ()):
                    if Megolm.matches(event):
                        with suppress(InvalidEvent):
                            users.add(TimelineEvent.from_dict(event).sender)

        await self.client.e2e.query_devices({u: [] for u in users})

        coro = self.client.e2e.handle_to_device_event
        await events_call(sync, "to_device", ToDeviceEvent, coro)

        # events_call(sync, "account_data", noop)  # TODO
        # events_call(sync, "presence", noop)      # TODO

        rooms = self.client.rooms

        async def set_room(room_id: RoomId) -> Room:
            if room_id in rooms._data:
                return rooms._data[room_id]

            path = self.client.rooms.room_path(room_id)
            room = await Room(path=path, client=self.client, id=room_id)

            rooms._data[room_id] = room
            return room

        for room_id, data in sync.get("rooms", {}).get("invite", {}).items():
            room         = await set_room(room_id)
            room.invited = True
            room.left    = False
            await room_events_call(data, "invite_state", room)

        for room_id, data in sync.get("rooms", {}).get("join", {}).items():
            room         = await set_room(room_id)
            # TODO: save when changing invited/left
            room.invited = False
            room.left    = False

            summary = data.get("summary", {})
            unread  = data.get("unread_notifications", {})

            if summary.get("m.heroes"):
                room.summary_heroes = tuple(summary["m.heroes"])

            if summary.get("m.joined_members_count"):
                room.summary_joined = summary["m.joined_members_count"]

            if summary.get("m.invited_members_count"):
                room.summary_invited = summary["m.invited_members_count"]

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
                    after = await decrypt(
                        TimelineEvent.from_dict(event), room.id,
                    )
                    break

            if limited and prev_batch and after:
                if not room.timeline:
                    await room.timeline.load_history(count=1)

                before_id = next(reversed(tuple(room.timeline)), None)
                await room.timeline.register_gap(
                    prev_batch, before_id, after.id, after.date,
                )

            # await events_call(data, "account_data", room.handle_event)
            # await events_call(data, "ephemeral", room.handle_event)
            await room_events_call(data, "state", room)
            await room_events_call(data, "timeline", room)

        for room_id, data in sync.get("rooms", {}).get("leave", {}).items():
            room      = await set_room(room_id)
            room.left = True
            # await events_call(data, "account_data", room.handle_event)
            await room_events_call(data, "state", room)
            await room_events_call(data, "timeline", room)

        if "device_one_time_keys_count" in sync:
            up = sync["device_one_time_keys_count"].get("signed_curve25519", 0)
            await self.client.e2e.upload_one_time_keys(currently_uploaded=up)

        self.next_batch = sync["next_batch"]
        await self.save()
