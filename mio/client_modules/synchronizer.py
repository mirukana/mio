import asyncio
import logging as log
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional, Set, Union

from ..events import Event, RoomEvent
from ..typing import RoomId, UserId
from ..utils import FileModel, remove_none
from .client_module import ClientModule
from .encryption.errors import DecryptionError
from .encryption.events import Megolm, Olm
from .rooms.room import Room

if TYPE_CHECKING:
    from ..base_client import Client

FilterType = Union[None, str, Dict[str, Any]]


class Synchronization(ClientModule, FileModel):
    next_batch: Optional[str] = None

    __json__ = {"exclude": {"client"}}


    @property
    def save_file(self) -> Path:
        return self.client.save_dir / "sync.json"


    @classmethod
    async def load(cls, client: "Client") -> "Synchronization":
        data = await cls._read_json(client.save_dir / "sync.json")
        return cls(client=client, **data)


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
            await self.handle_sync(result)
            self.next_batch = result["next_batch"]
            await self._save()


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

        async def decrypt(event: Event, room_id: RoomId) -> Event:
            if not isinstance(event, (Olm, Megolm)):
                return event

            try:
                return await self.client.e2e.decrypt_event(event, room_id)
            except DecryptionError as e:
                log.warn("Failed decrypting %r: %r\n", event, e)
                return event

        async def events_call(data: dict, key: str, coro: Callable) -> None:
            for event in data.get(key, {}).get("events", ()):
                Event.subtype_from_matrix(event)
                await coro(await decrypt(ev, room.id))

        async def room_events_call(data: dict, key: str, room: Room) -> None:
            for event in data.get(key, {}).get("events", ()):
                ev       = Event.subtype_from_matrix(event)
                is_state = key in ("state", "invite_state")
                await room.handle_event(await decrypt(ev, room.id), is_state)

        users: Set[UserId] = set()

        for event in sync.get("to_device", {}).get("events", ()):
            if Olm.matches_event(event):
                parsed = Olm.from_matrix(event)
                if isinstance(parsed, Olm):
                    users.add(parsed.sender)

        for kind in ("invite", "join", "leave"):
            for data in sync.get("rooms", {}).get(kind, {}).values():
                for event in data.get("timeline", {}).get("events", ()):
                    if Megolm.matches_event(event):
                        parsed = Megolm.from_matrix(event)
                        if isinstance(parsed, Megolm) and parsed.sender:
                            users.add(parsed.sender)

        await self.client.e2e.query_devices({u: [] for u in users})

        coro = self.client.e2e.handle_to_device_event
        await events_call(sync, "to_device", coro)

        # events_call(sync, "account_data", noop)  # TODO
        # events_call(sync, "presence", noop)      # TODO

        rooms = self.client.rooms

        async def set_room(room_id: str) -> Room:
            if room_id in rooms._data:
                return rooms._data[room_id]

            room = await Room(client=self.client, id=room_id)
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
            after      = None

            for event in timeline.get("events", []):
                ev = await decrypt(Event.subtype_from_matrix(event), room.id)
                if isinstance(ev, RoomEvent) and ev.event_id and ev.date:
                    after = ev
                    break

            if limited and prev_batch and after:
                if not room.timeline:
                    await room.timeline.load_history(events_count=1)

                before_id = next(reversed(tuple(room.timeline)), None)
                await room.timeline.add_gap(
                    prev_batch,
                    before_id,
                    after.event_id,  # type: ignore
                    after.date,      # type: ignore
                )

            await events_call(data, "account_data", room.handle_event)
            await events_call(data, "ephemeral", room.handle_event)
            await room_events_call(data, "state", room)
            await room_events_call(data, "timeline", room)

        for room_id, data in sync.get("rooms", {}).get("leave", {}).items():
            room      = await set_room(room_id)
            room.left = True
            await events_call(data, "account_data", room.handle_event)
            await room_events_call(data, "state", room)
            await room_events_call(data, "timeline", room)

        if "device_one_time_keys_count" in sync:
            up = sync["device_one_time_keys_count"].get("signed_curve25519", 0)
            await self.client.e2e.upload_one_time_keys(currently_uploaded=up)
