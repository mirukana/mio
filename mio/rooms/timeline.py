# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

import json
from dataclasses import dataclass, field
from datetime import datetime
from itertools import groupby
from typing import TYPE_CHECKING, Dict, Iterable, List, Optional, Set, Tuple
from uuid import uuid4

import aiofiles
from aiopath import AsyncPath
from sortedcollections import ValueSortedDict

from ..core.contents import EventContent
from ..core.data import JSON, IndexableMap, JSONFile, Parent, Runtime
from ..core.events import InvalidEvent
from ..core.files import atomic_write
from ..core.ids import EventId
from ..core.utils import remove_none
from ..e2e.contents import Megolm
from ..filters import LAZY_LOAD as LAZY
from ..filters import Filter
from .contents.settings import Creation
from .events import SendStep, StateEvent, TimelineEvent

if TYPE_CHECKING:
    from ..client import Client
    from .room import Room

InGroupSessionKey = Tuple[str, str]  # (sender_curve25519, session_id)
UndecryptedEvents = Dict[InGroupSessionKey, List[TimelineEvent[Megolm]]]


@dataclass
class Timeline(JSONFile, IndexableMap[EventId, TimelineEvent]):
    room: Parent["Room"]       = field(repr=False)
    gaps: Dict[EventId, "Gap"] = field(default_factory=ValueSortedDict)

    _data: Runtime[Dict[EventId, TimelineEvent]] = field(
        default_factory=ValueSortedDict,
    )

    _undecrypted: Runtime[UndecryptedEvents] = field(
        init=False, repr=False, default_factory=dict,
    )

    _loaded_files: Runtime[Set[AsyncPath]] = field(
        init=False, default_factory=set,
    )


    @property
    def path(self) -> AsyncPath:
        return self.room.path.parent / "timeline.json"


    @property
    def fully_loaded(self) -> bool:
        return not self.gaps


    @property
    def unsent_past_events(self) -> Iterable[TimelineEvent]:
        for event in self.values():
            if event.historic and event.sending != SendStep.synced:
                yield event


    async def load_event(self, event_id: EventId) -> TimelineEvent:
        if event_id in self:
            return self[event_id]

        url   = self.room.net.api / "rooms" / self.room.id / "event" / event_id
        reply = await self.room.net.get(url)

        event: TimelineEvent
        event = TimelineEvent.from_dict(reply.json, parent=self.room)
        event.historic = True
        await self._register_events(event)
        return event


    async def load_history(
        self, count: int = 100, filter: Optional[Filter] = LAZY,
    ) -> List[TimelineEvent]:

        disk_loaded: List[TimelineEvent] = []
        loaded:      List[TimelineEvent] = await self._fill_newest_gap(
            count, filter,
        )

        day_dirs = sorted(  # noqa
            [path async for path in self.path.parent.glob("????-??-??")],
            key = lambda d: d.name,
        )

        for day_dir in reversed(day_dirs):
            if len(loaded) >= count:
                break

            hour_files = sorted(  # noqa
                [path async for path in day_dir.glob("??h.json")],
                key = lambda f: f.name,
            )

            for hour_file in reversed(hour_files):
                if hour_file in self._loaded_files:
                    continue

                self.room.client.debug("Loading events from {}", hour_file)
                events = json.loads(await hour_file.read_text())

                self._loaded_files.add(hour_file)

                for source in events:
                    ev: TimelineEvent

                    with self.room.client.report(InvalidEvent, trace=True):
                        ev = TimelineEvent.from_dict(source, self.room)
                        ev = await ev._decrypted()

                        ev.historic = True

                        disk_loaded.append(ev)
                        loaded.append(ev)

                if len(loaded) >= count:
                    break

        await self._register_events(*disk_loaded, _save=False)
        return loaded


    async def send(
        self,
        content:        EventContent,
        local_echo_to:  Optional[List["Client"]] = None,
        transaction_id: Optional[str]            = None,
    ) -> EventId:

        room   = self.room
        client = room.client

        if room.state.encryption and not isinstance(content, Megolm):
            if not room.state.all_users_loaded:
                await room.state.load_all_users()

            content = await client.e2e._encrypt_room_event(
                room_id   = room.id,
                for_users = room.state.members,
                settings  = room.state.encryption,
                content   = content,
            )

        assert content.type
        tx  = transaction_id if transaction_id else str(uuid4())
        url = client.net.api / "rooms" / room.id / "send" / content.type / tx

        if local_echo_to is None:
            local_echo_to = [client]

        echo = await TimelineEvent.from_dict({
            "type":             content.type,
            "content":          content.dict,
            "event_id":         f"$echo.{tx}",
            "sender":           client.user_id,
            "origin_server_ts": datetime.now().timestamp() * 1000,
            "unsigned":         {"transaction_id": tx},
        }, parent=room)._decrypted()
        echo.sending = SendStep.sending

        for eclient in local_echo_to:
            if room.id in eclient.rooms:
                await eclient.rooms[room.id].timeline._register_events(echo)

        reply    = await client.net.put(url, content.dict)
        event_id = EventId(reply.json["event_id"])

        for eclient in local_echo_to:
            if room.id in eclient.rooms:
                timeline           = eclient.rooms[room.id].timeline
                sent               = SendStep.sent
                old: TimelineEvent = timeline._data.pop(echo.id)
                new: TimelineEvent = old.but(id=event_id, sending=sent)
                await timeline._register_events(new)

        return event_id


    def _get_event_file(self, event: TimelineEvent) -> AsyncPath:
        return self.path.parent / event.date.strftime("%Y-%m-%d/%Hh.json")


    async def _register_gap(
        self,
        fill_token:       str,
        event_before:     Optional[EventId],
        event_after:      EventId,
        event_after_date: datetime,
    ) -> None:

        self.gaps[event_after] = Gap(
            room             = self.room,
            fill_token       = fill_token,
            event_before     = event_before,
            event_after      = event_after,
            event_after_date = event_after_date,
        )
        await self.save()


    async def _register_events(
        self, *events: TimelineEvent, _save: bool = True,
    ) -> None:

        for event in events:
            self._data[event.id] = event

            if isinstance(event.content, Megolm):
                content = event.content
                key     = (content.sender_curve25519, content.session_id)
                self._undecrypted.setdefault(key, []).append(event)

            await self.room._call_callbacks(event)

        if not _save:
            return

        for path, event_group in groupby(events, key=self._get_event_file):
            sorted_group = sorted(event_group)
            event_dicts  = [e.dict for e in sorted_group]

            if not await path.exists():
                await path.parent.mkdir(parents=True, exist_ok=True)
                async with atomic_write(path) as output:
                    await output.write("[]")  # type: ignore

            async with aiofiles.open(path, "r") as file:
                evs  = json.loads(await file.read())
                evs += event_dicts

            async with atomic_write(path, "w") as file2:
                dump = json.dumps(evs, indent=4, ensure_ascii=False)
                await file2.write(dump)  # type: ignore

            self._loaded_files.add(path)


    async def _fill_newest_gap(
        self, min_events: int, filter: Optional[Filter] = LAZY,
    ) -> List[TimelineEvent]:

        gap = next(
            (v for k, v in reversed(list(self.gaps.items())) if k in self),
            None,
        )

        if not gap or gap.event_after not in self:
            return []

        events: List[TimelineEvent] = []

        while not gap.filled and len(events) < min_events:
            events += await gap.fill(min_events, filter)

        return events


    async def _retry_decrypt(self, *sessions: InGroupSessionKey) -> None:
        decrypted = []
        self.room.client.debug(
            "{}: retry decrypting events for {}", self.room.id, sessions,
        )

        for key in sessions:
            for event in self._undecrypted.get(key, []):
                event2 = await event._decrypted()
                if not isinstance(event2.content, Megolm):
                    decrypted.append(event2)

        if decrypted:
            self.room.client.info(
                "{}: {} events decrypted after retry",
                self.room.id, len(decrypted),
            )
            await self._register_events(*decrypted)


@dataclass
class Gap(JSON):
    room:             Parent["Room"] = field(repr=False)
    fill_token:       str
    event_before:     Optional[EventId]
    event_after:      EventId
    event_after_date: datetime
    filled:           bool = False


    def __lt__(self, other: "Gap") -> bool:
        return self.event_after_date < other.event_after_date


    async def fill(
        self, max_events: Optional[int] = 100, filter: Optional[Filter] = LAZY,
    ) -> List[TimelineEvent]:

        if self.event_after not in self.room.timeline.gaps:
            return []

        url   = self.room.net.api / "rooms" / self.room.id / "messages"
        reply = await self.room.net.get(url % remove_none({
            "from":   self.fill_token,
            "dir":    "b",  # direction: backwards
            "limit":  max_events,
            "filter": filter.json if filter else None,  # API rejects IDs
        }))

        state_evs: List[StateEvent] = []

        for source in reply.json.get("state", []):
            with self.room.client.report(InvalidEvent):
                state_evs.append(StateEvent.from_dict(source, self.room))

        await self.room.state._register(*state_evs)

        if not reply.json.get("chunk"):
            self.filled = True
            self.room.timeline.gaps.pop(self.event_after, None)
            await self.room.timeline.save()
            return []

        evs: List[TimelineEvent] = []

        for source in reply.json["chunk"]:
            ev: TimelineEvent

            with self.room.client.report(InvalidEvent):
                ev = TimelineEvent.from_dict(source, self.room)
                ev = await ev._decrypted()

                ev.historic = True
                evs.append(ev)

        await self.room.timeline._register_events(*evs)

        if any(
            isinstance(e.content, Creation) or e.id == self.event_before
            for e in evs
        ):
            self.filled = True
            self.room.timeline.gaps.pop(self.event_after, None)
        else:
            self.event_after = evs[-1].id

        self.fill_token = reply.json["end"]
        await self.room.timeline.save()
        return evs
