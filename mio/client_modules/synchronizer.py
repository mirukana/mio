import asyncio
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Union

from ..events import Event
from ..utils import remove_none
from . import ClientModule
from .rooms import InvitedRoom, JoinedRoom, LeftRoom

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
        result = await self.client.json_send(
            method     = "GET",
            url        = f"{self.client.api}/sync",
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
        # TODO: to_device, device_lists, device_one_time_keys_count

        async def events_call(data: dict, key: str, coro: Callable) -> None:
            for event in data.get(key, {}).get("events", ()):
                await coro(Event.subtype_from_source(event))

        # events_call(sync, "account_data", noop)  # TODO
        # events_call(sync, "presence", noop)      # TODO

        rooms = self.client.rooms

        for room_id, data in sync.get("rooms", {}).get("invite", {}).items():
            invited = rooms.invited.setdefault(room_id, InvitedRoom(room_id))
            await events_call(data, "invite_state", invited.handle_event)

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
            await events_call(data, "state", joined.handle_event)
            await events_call(data, "timeline", joined.handle_event)
            await events_call(data, "ephemeral", joined.handle_event)

        for room_id, data in sync.get("rooms", {}).get("leave", {}).items():
            left = rooms.left.setdefault(room_id, LeftRoom(room_id))
            await events_call(data, "account_data", left.handle_event)
            await events_call(data, "state", left.handle_event)
            await events_call(data, "timeline", left.handle_event)
