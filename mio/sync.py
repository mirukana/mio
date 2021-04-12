import asyncio
import json
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    TYPE_CHECKING, Any, Awaitable, Callable, Dict, Iterator, List, Optional,
    Set, Type, Union,
)

from .core.data import Parent, Runtime
from .core.events import Event, InvalidEvent
from .core.types import RoomId, UserId
from .core.utils import get_logger, log_errors, make_awaitable, remove_none
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

LOG = get_logger()

FilterType       = Union[None, str, Dict[str, Any]]
ExceptionHandler = Callable[[Exception], Optional[Awaitable[None]]]


@dataclass
class Sync(JSONClientModule):
    client:     Parent["Client"] = field(repr=False)
    next_batch: Optional[str]    = None
    paused:     Runtime[bool]    = False


    @property
    def path(self) -> Path:
        return self.client.path.parent / "sync.json"


    async def once(
        self,
        timeout:      float          = 0,
        sync_filter:  FilterType     = None,
        since:        Optional[str]  = None,
        full_state:   Optional[bool] = None,
        set_presence: Optional[str]  = None,
    ) -> Optional[dict]:

        filter_param: Any = None

        if sync_filter:
            filter_param = json.dumps(sync_filter, ensure_ascii=False)

        url = self.client.api / "sync" % remove_none({
            "timeout":      int(timeout * 1000),
            "filter":       filter_param,
            "since":        since or self.next_batch,
            "full_state":   full_state,
            "set_presence": set_presence,
            # or self.client.presence.to_set TODO
        })

        # TODO: client-side timeout
        result = await self.client.send_json("GET", url)

        if self.next_batch != result["next_batch"]:
            await self._handle_sync(result)
            return result

        return None


    async def loop(
        self,
        timeout:             float                      = 10,
        sync_filter:         FilterType                 = None,
        first_sync_filter:   FilterType                 = None,
        since:               Optional[str]              = None,
        full_state:          Optional[bool]             = None,
        set_presence:        Optional[str]              = None,
        sleep_between_syncs: float                      = 1,
        exception_handler:   Optional[ExceptionHandler] = None,
    ) -> None:

        first_run         = True
        exception_handler = exception_handler or (lambda _: None)

        while True:
            use_filter = first_sync_filter if first_run else sync_filter

            try:
                await self.once(timeout, use_filter, None, None, set_presence)
            except Exception as e:
                LOG.exception("Error in server sync loop")
                await make_awaitable(exception_handler(e))
            else:
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
        # TODO: account_data, presence

        while self.paused:
            await asyncio.sleep(0.1)

        state_member_events: List[StateEvent[Member]] = []

        async def events_call(
            data: dict, key: str, evtype: Type[Event], coro: Callable,
        ) -> None:
            for event in data.get(key, {}).get("events", ()):
                with log_errors(InvalidEvent):
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
                with log_errors(InvalidEvent):
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

        e2e_senders: Set[UserId] = set()

        for event in sync.get("to_device", {}).get("events", ()):
            if Olm.matches(event):
                with suppress(InvalidEvent):
                    e2e_senders.add(UserId(event["sender"]))

        for kind in ("invite", "join"):
            for data in sync.get("rooms", {}).get(kind, {}).values():
                for event in data.get("timeline", {}).get("events", ()):
                    if Megolm.matches(event):
                        with suppress(InvalidEvent):
                            e2e_senders.add(UserId(event["sender"]))

        await self.client.devices.ensure_tracked(e2e_senders)

        changed = sync.get("device_lists", {}).get("changed", [])
        await self.client.devices.update({UserId(c) for c in changed})

        to_call = self.client.devices._call_callbacks
        await events_call(sync, "to_device", ToDeviceEvent, to_call)

        rooms = self.client.rooms

        async def set_room(room_id: RoomId) -> Room:
            if room_id in rooms._data:
                return rooms._data[room_id]

            rooms._data[room_id] = Room(client=self.client, id=room_id)
            return rooms._data[room_id]

        for room_id, data in sync.get("rooms", {}).get("invite", {}).items():
            room         = await set_room(RoomId(room_id))
            room.invited = True
            room.left    = False
            await room_events_call(data, "invite_state", room)

        for room_id, data in sync.get("rooms", {}).get("join", {}).items():
            room         = await set_room(RoomId(room_id))
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
                    after = TimelineEvent.from_dict(event, room)
                    after = await after._decrypted()
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

        for room_id, data in sync.get("rooms", {}).get("leave", {}).items():
            if room_id in self.client.rooms.forgotten:
                continue

            room      = await set_room(RoomId(room_id))
            room.left = True
            # await events_call(data, "account_data", room.handle_event)
            await room_events_call(data, "state", room)
            await room_events_call(data, "timeline", room)

        no_more_shared_e2e_room = sync.get("device_lists", {}).get("left", [])
        self.client.devices.drop(*[UserId(u) for u in no_more_shared_e2e_room])

        if "device_one_time_keys_count" in sync:
            up = sync["device_one_time_keys_count"].get("signed_curve25519", 0)
            await self.client._e2e.upload_one_time_keys(currently_uploaded=up)

        await self.client.profile._update_on_sync(*state_member_events)

        self.next_batch = sync["next_batch"]
        await self.save()
