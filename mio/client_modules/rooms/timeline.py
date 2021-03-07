import json
import logging as log
from dataclasses import dataclass, field
from datetime import datetime
from itertools import groupby
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Set
from uuid import uuid4

from aiofiles import open as aiopen
from sortedcollections import ValueSortedDict

from ...client_modules.encryption.events import Megolm
from ...events.base_events import Content, InvalidEvent, TimelineEvent
from ...events.room_state import Creation
from ...typing import EventId
from ...utils import (
    JSON, Frozen, JSONFile, Map, Runtime, log_errors, remove_none,
)

if TYPE_CHECKING:
    from .room import Room


@dataclass
class Gap(JSON):
    fill_token:       str
    event_before:     Optional[EventId]
    event_after:      EventId
    event_after_date: datetime
    filled:           bool = False

    timeline: Runtime[Optional["Timeline"]] = field(default=None, repr=False)


    def __lt__(self, other: "Gap") -> bool:
        return self.event_after_date < other.event_after_date


    async def fill(
        self, max_events: Optional[int] = 100,
    ) -> List[TimelineEvent]:
        assert self.timeline

        if self.event_after not in self.timeline.gaps:
            return []

        client = self.timeline.room.client
        result = await client.send_json(
            method = "GET",
            path   = [*client.api, "rooms", self.timeline.room.id, "messages"],

            parameters = remove_none({
                "from":  self.fill_token,
                "dir":   "b",  # direction: backwards
                "limit": max_events,
            }),
        )

        # for event in result.get("state", [])  # TODO (for lazy loading)

        if not result.get("chunk"):
            self.filled = True
            self.timeline.gaps.pop(self.event_after, None)
            await self.timeline.save()
            return []

        evs: List[TimelineEvent] = []

        for ev in result["chunk"]:
            with log_errors(InvalidEvent):
                evs.append(TimelineEvent.from_dict(ev))

        await self.timeline.register_events(*evs)

        if any(
            isinstance(e.content, Creation) or e.id == self.event_before
            for e in evs
        ):
            self.filled = True
            self.timeline.gaps.pop(self.event_after, None)
        else:
            self.event_after = result["chunk"][-1]

        self.fill_token = result["end"]
        await self.timeline.save()
        return evs


@dataclass
class Timeline(JSONFile, Frozen, Map[EventId, TimelineEvent]):
    json_exclude = {"path", "room", "_loaded_files", "_data"}

    room: Runtime["Room"]    = field(repr=False)
    gaps: Dict[EventId, Gap] = field(default_factory=ValueSortedDict)

    _loaded_files: Runtime[Set[Path]] = field(default_factory=set)

    _data: Runtime[Dict[EventId, TimelineEvent]] = \
        field(default_factory=ValueSortedDict)


    def __post_init__(self) -> None:
        # TODO: make them JSONFile instead of doing this workaround
        for gap in self.gaps.values():
            gap.timeline = self


    @property
    def fully_loaded(self) -> bool:
        return not self.gaps


    def get_event_file(self, event: TimelineEvent) -> Path:
        assert event.date
        return self.path.parent / event.date.strftime("%Y-%m-%d/%Hh.json")


    async def register_gap(
        self,
        fill_token:       str,
        event_before:     Optional[EventId],
        event_after:      EventId,
        event_after_date: datetime,
    ) -> None:
        self.gaps[event_after] = Gap(
            timeline         = self,
            fill_token       = fill_token,
            event_before     = event_before,
            event_after      = event_after,
            event_after_date = event_after_date,
        )
        await self.save()


    async def register_events(self, *events: TimelineEvent) -> None:
        for event in events:
            self._data[event.id] = event

        for path, event_group in groupby(events, key=self.get_event_file):
            sorted_group = sorted(event_group)
            event_dicts  = [e.dict for e in sorted_group]

            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)

                async with aiopen(path, "w") as file:
                    await file.write("[]")

            async with aiopen(path, "r+") as file:
                evs  = json.loads(await file.read())
                evs += event_dicts
                await file.seek(0)
                await file.write(json.dumps(evs, indent=4, ensure_ascii=False))

            self._loaded_files.add(path)


    async def load_history(self, count: int = 100) -> List[TimelineEvent]:
        loaded: List[TimelineEvent] = await self._fill_newest_gap(count)

        day_dirs = sorted(
            self.path.parent.glob("????-??-??"), key=lambda d: d.name,
        )

        for day_dir in reversed(day_dirs):
            if len(loaded) >= count:
                break

            hour_files = sorted(day_dir.glob("??h.json"), key=lambda f: f.name)

            for hour_file in reversed(hour_files):
                if hour_file in self._loaded_files:
                    continue

                async with aiopen(hour_file) as file:
                    log.debug("Loading events from %s", hour_file)
                    events = json.loads(await file.read())

                self._loaded_files.add(hour_file)

                for ev in events:
                    with log_errors(InvalidEvent, trace=True):
                        loaded.append(TimelineEvent.from_dict(ev))

                if len(loaded) >= count:
                    break

        self._data.update({e.id: e for e in loaded})
        return loaded


    async def send(
        self, content: Content, transaction_id: Optional[str] = None,
    ) -> str:
        room = self.room

        if room.state.encryption and not isinstance(content, Megolm):
            content = await room.client.e2e.encrypt_room_event(
                room_id   = room.id,
                for_users = room.state.members,
                settings  = room.state.encryption.content,
                content   = content,
            )

        assert content.type
        tx   = transaction_id if transaction_id else str(uuid4())
        path = [*room.client.api, "rooms", room.id, "send", content.type, tx]

        result = await room.client.send_json("PUT", path, body=content.dict)
        return result["event_id"]


    async def _fill_newest_gap(self, min_events: int) -> List[TimelineEvent]:
        gap = next(
            (v for k, v in reversed(list(self.gaps.items())) if k in self),
            None,
        )

        if not gap or gap.event_after not in self:
            return []

        events: List[TimelineEvent] = []

        while not gap.filled and len(events) < min_events:
            events += await gap.fill(min_events)

        return events
