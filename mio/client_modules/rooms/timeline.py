from __future__ import annotations

import json
import logging as log
from datetime import datetime
from itertools import groupby
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from aiofiles import open as aiopen
from pydantic import PrivateAttr
from sortedcollections import ValueSortedDict

from ...events.base_events import RoomEvent
from ...events.room_state import Creation
from ...typing import EventId
from ...utils import AsyncInit, FileModel, MapModel, Model, remove_none


class Gap(Model):
    room:             Room
    fill_token:       str
    event_before:     Optional[EventId]
    event_after:      EventId
    event_after_date: datetime
    filled:           bool = False

    __json__         = {"exclude": {"room"}}
    __repr_exclude__ = {"room"}


    def __lt__(self, other: "Gap") -> bool:
        return self.event_after_date < other.event_after_date


    async def fill(self, max_events: Optional[int] = 100) -> List[RoomEvent]:
        if self.event_after not in self.room.timeline.gaps:
            return []

        client = self.room.client
        result = await client.send_json(
            method = "GET",
            path   = [*client.api, "rooms", self.room.id, "messages"],

            parameters = remove_none({
                "from":  self.fill_token,
                "dir":   "b",  # direction: backwards
                "limit": max_events,
            }),
        )

        # for event in result.get("state", [])  # TODO (for lazy loading)

        if not result.get("chunk"):
            self.filled = True
            self.room.timeline.gaps.pop(self.event_after, None)
            await self.room.timeline._save()
            return []

        evs      = [RoomEvent.subtype_from_matrix(e) for e in result["chunk"]]
        room_evs = [e for e in evs if isinstance(e, RoomEvent)]
        await self.room.timeline.add_events(*room_evs)

        if any(
            isinstance(e, Creation) or e.event_id == self.event_before
            for e in room_evs
        ):
            self.filled = True
            self.room.timeline.gaps.pop(self.event_after, None)
        else:
            self.event_after = result["chunk"][-1]

        self.fill_token = result["end"]
        await self.room.timeline._save()
        return room_evs


class Timeline(FileModel, MapModel, AsyncInit):
    room: Room
    gaps: Dict[EventId, Gap] = ValueSortedDict()  # {gap.event_after: gap}

    _loaded_files: Set[Path]                = PrivateAttr(set())
    _data:         Dict[EventId, RoomEvent] = PrivateAttr(ValueSortedDict())

    __repr_exclude__ = {"room"}


    def __json__(self) -> Dict[str, Any]:  # type: ignore
        return {
            "exclude": {"room": ..., "gaps": {k: {"room"} for k in self.gaps}},
        }


    @property
    def fully_loaded(self) -> bool:
        return not self.gaps


    @property
    def save_file(self) -> Path:
        return self.room.save_file.parent / "timeline.json"


    @classmethod
    async def load(cls, room: Room) -> "Timeline":
        file = room.save_file.parent / "timeline.json"
        data = await cls._read_json(file)

        data["gaps"] = {
            k: Gap(room=room, **v) for k, v in data.get("gaps", {}).items()
        }

        return cls(room=room, **data)


    def get_event_file(self, event: RoomEvent) -> Path:
        assert event.date
        return self.save_file.parent / event.date.strftime("%Y-%m-%d/%Hh.json")


    async def add_gap(
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
        await self._save()


    async def add_events(self, *events: RoomEvent) -> None:
        for event in events:
            assert event.event_id and event.date
            self._data[event.event_id] = event

        for path, event_group in groupby(events, key=self.get_event_file):
            event_dicts = [json.loads(e.json()) for e in event_group]
            event_dicts.sort(key=lambda e: e["date"])

            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)

                async with aiopen(path, "w") as file:  # type: ignore
                    await file.write("[]")

            async with aiopen(path, "r+") as file:  # type: ignore
                evs  = json.loads(await file.read())
                evs += event_dicts
                await file.seek(0)
                await file.write(json.dumps(evs, indent=4, ensure_ascii=False))

            self._loaded_files.add(path)


    async def load_history(self, events_count: int = 100) -> List[RoomEvent]:
        loaded: List[RoomEvent] = await self._fill_newest_gap(events_count)

        day_dirs = sorted(
            self.save_file.parent.glob("????-??-??"), key=lambda d: d.name,
        )

        for day_dir in reversed(day_dirs):
            if len(loaded) >= events_count:
                break

            hour_files = sorted(day_dir.glob("??h.json"), key=lambda f: f.name)

            for hour_file in reversed(hour_files):
                if hour_file in self._loaded_files:
                    continue

                async with aiopen(hour_file) as file:  # type: ignore
                    log.debug("Loading events from %s", hour_file)
                    events = json.loads(await file.read())

                self._loaded_files.add(hour_file)

                for ev in events:
                    event = RoomEvent.subtype_from_fields(ev)
                    if isinstance(event, RoomEvent) and event.event_id:
                        loaded.append(event)

                if len(loaded) >= events_count:
                    break

        self._data.update({e.event_id: e for e in loaded if e.event_id})
        return loaded


    async def _fill_newest_gap(self, min_events: int) -> List[RoomEvent]:
        gap = next(
            (v for k, v in reversed(list(self.gaps.items())) if k in self),
            None,
        )

        if not gap or gap.event_after not in self:
            return []

        events: List[RoomEvent] = []

        while not gap.filled and len(events) < min_events:
            events += await gap.fill(min_events)

        return events


from .room import Room

Gap.update_forward_refs()
Timeline.update_forward_refs()
