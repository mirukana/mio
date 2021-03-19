import json
from dataclasses import dataclass, field
from datetime import datetime
from itertools import groupby
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Set
from uuid import uuid4

from aiofiles import open as aiopen
from sortedcollections import ValueSortedDict

from ..core.contents import EventContent
from ..core.data import JSON, IndexableMap, JSONFile, Parent, Runtime
from ..core.events import InvalidEvent
from ..core.types import EventId
from ..core.utils import get_logger, log_errors, remove_none
from ..e2e.contents import Megolm
from ..e2e.errors import DecryptionError
from .contents.settings import Creation
from .events import TimelineEvent

if TYPE_CHECKING:
    from .room import Room

LOG = get_logger()


@dataclass
class Timeline(JSONFile, IndexableMap[EventId, TimelineEvent]):
    room: Parent["Room"]       = field(repr=False)
    gaps: Dict[EventId, "Gap"] = field(default_factory=ValueSortedDict)

    _loaded_files: Runtime[Set[Path]] = field(default_factory=set)

    _data: Runtime[Dict[EventId, TimelineEvent]] = \
        field(default_factory=ValueSortedDict)


    @property
    def fully_loaded(self) -> bool:
        return not self.gaps


    @classmethod
    def get_path(cls, parent: "Room", **kwargs) -> Path:
        return parent.path.parent / "timeline.json"


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
            room             = self.room,
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
                    LOG.debug("Loading events from %s", hour_file)
                    events = json.loads(await file.read())

                self._loaded_files.add(hour_file)

                for source in events:
                    ev: TimelineEvent

                    with log_errors(InvalidEvent, trace=True):
                        ev = TimelineEvent.from_dict(source, self.room)

                    with log_errors(DecryptionError):
                        ev = await ev.decrypted()

                    loaded.append(ev)

                if len(loaded) >= count:
                    break

        self._data.update({e.id: e for e in loaded})
        return loaded


    async def send(
        self, content: EventContent, transaction_id: Optional[str] = None,
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
        self, max_events: Optional[int] = 100,
    ) -> List[TimelineEvent]:

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
            await self.room.timeline.save()
            return []

        evs: List[TimelineEvent] = []

        for source in result["chunk"]:
            ev: TimelineEvent

            with log_errors(InvalidEvent):
                ev = TimelineEvent.from_dict(source, self.room)

            with log_errors(DecryptionError):
                ev = await ev.decrypted()

            evs.append(ev)

        await self.room.timeline.register_events(*evs)

        if any(
            isinstance(e.content, Creation) or e.id == self.event_before
            for e in evs
        ):
            self.filled = True
            self.room.timeline.gaps.pop(self.event_after, None)
        else:
            self.event_after = result["chunk"][-1]

        self.fill_token = result["end"]
        await self.room.timeline.save()
        return evs
