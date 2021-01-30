import asyncio
import logging as log
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Set, Union

from ..events import Event, RoomEvent
from ..utils import remove_none
from . import ClientModule, InvitedRoom, JoinedRoom, LeftRoom, Room
from .encryption.errors import DecryptionError
from .encryption.events import Megolm, Olm

FilterType = Union[None, str, Dict[str, Any]]


@dataclass
class Synchronization(ClientModule):
    next_batch: Optional[str] = None


    async def sync(
        self,
        timeout:      Optional[int]  = 0,
        sync_filter:  FilterType     = None,
        since:        Optional[str]  = None,
        full_state:   Optional[bool] = None,
        set_presence: Optional[str]  = None,
    ) -> None:

        parameters = {
            "timeout":      timeout,
            "filter":       sync_filter,
            # or self.loaded_sync_token TODO
            "since":        since or self.next_batch,
            "full_state":   full_state,
            # or self.client.presence.to_set TODO
            "set_presence": set_presence,
        }

        # TODO: timeout
        result = await self.client.send_json(
            method     = "GET",
            path       = [*self.client.api, "sync"],
            parameters = remove_none(parameters),
        )

        if self.next_batch != result["next_batch"]:
            self.next_batch = result["next_batch"]
            await self.handle_sync(result)


    async def loop(
        self,
        timeout:                     Optional[int]  = 0,
        sync_filter:                 FilterType     = None,
        first_sync_filter:           FilterType     = None,
        since:                       Optional[str]  = None,
        full_state:                  Optional[bool] = None,
        set_presence:                Optional[str]  = None,
        sleep_seconds_between_syncs: float          = 0,
    ) -> None:

        await self.sync(0, first_sync_filter, since, full_state, set_presence)

        while True:
            await self.sync(timeout, sync_filter, None, None, set_presence)
            await asyncio.sleep(sleep_seconds_between_syncs)


    async def handle_sync(self, sync: Dict[str, Any]) -> None:
        # TODO: handle event parsing errors, device_lists

        async def decrypt(
            event: Union[Olm, Megolm], room_id: Optional[str] = None,
        ) -> Event:
            try:
                return await self.client.e2e.decrypt_event(event, room_id)
            except DecryptionError as e:
                event.decryption_error = e
                log.warn("Failed decrypting %r\n", event)
                return event

        async def events_call(data: dict, key: str, coro: Callable) -> None:
            for event in data.get(key, {}).get("events", ()):
                if self.client.e2e.ready and Olm.matches_event(event):
                    parsed = Olm.from_source(event)
                    if isinstance(parsed, Olm):
                        await coro(await decrypt(parsed))
                    else:
                        await coro(parsed)
                else:
                    await coro(Event.subtype_from_source(event))

        async def room_events_call(data: dict, key: str, room: Room) -> None:
            for event in data.get(key, {}).get("events", ()):
                if self.client.e2e.ready and Megolm.matches_event(event):
                    clear = Megolm.from_source(event)
                    if isinstance(clear, Megolm):
                        clear = await decrypt(clear, room.id)
                else:
                    clear = RoomEvent.subtype_from_source(event)

                await room.handle_event(clear)

        if self.client.e2e.ready:
            users: Set[str] = set()

            for event in sync.get("to_device", {}).get("events", ()):
                if Olm.matches_event(event):
                    parsed = Olm.from_source(event)
                    if isinstance(parsed, Olm):
                        users.add(parsed.sender)

            for kind in ("invite", "join", "leave"):
                for data in sync.get("rooms", {}).get(kind, {}).values():
                    for event in data.get("timeline", {}).get("events", ()):
                        if Megolm.matches_event(event):
                            parsed = Megolm.from_source(event)
                            if isinstance(parsed, Megolm):
                                users.add(parsed.sender)

            await self.client.e2e.query_devices(users)

            coro = self.client.e2e.handle_to_device_event
            await events_call(sync, "to_device", coro)

        # events_call(sync, "account_data", noop)  # TODO
        # events_call(sync, "presence", noop)      # TODO

        rooms = self.client.rooms

        for room_id, data in sync.get("rooms", {}).get("invite", {}).items():
            invited = rooms.invited.setdefault(room_id, InvitedRoom(room_id))
            await room_events_call(data, "invite_state", invited)

        for room_id, data in sync.get("rooms", {}).get("join", {}).items():
            joined = rooms.joined.setdefault(room_id, JoinedRoom(room_id))

            prev_batch = data.get("timeline", {}).get("prev_batch")
            summary    = data.get("summary", {})
            unread     = data.get("unread_notifications", {})

            if prev_batch and not joined.scrollback_token:
                joined.scrollback_token = prev_batch

            if summary.get("m.heroes"):
                joined.summary_heroes = tuple(summary["m.heroes"])

            if summary.get("m.joined_members_count"):
                joined.summary_joined = summary["m.joined_members_count"]

            if summary.get("m.invited_members_count"):
                joined.summary_invited = summary["m.invited_members_count"]

            if unread.get("notification_count"):
                joined.unread_notifications = unread["notification_count"]

            if unread.get("highlight_count"):
                joined.unread_highlights = unread["highlight_count"]

            await events_call(data, "account_data", joined.handle_event)
            await events_call(data, "ephemeral", joined.handle_event)
            await room_events_call(data, "state", joined)
            await room_events_call(data, "timeline", joined)

        for room_id, data in sync.get("rooms", {}).get("leave", {}).items():
            left = rooms.left.setdefault(room_id, LeftRoom(room_id))
            await events_call(data, "account_data", left.handle_event)
            await room_events_call(data, "state", left)
            await room_events_call(data, "timeline", left)

        if self.client.e2e.ready and "device_one_time_keys_count" in sync:
            up = sync["device_one_time_keys_count"].get("signed_curve25519", 0)
            await self.client.e2e.upload_one_time_keys(currently_uploaded=up)
