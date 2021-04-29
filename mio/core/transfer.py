# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Awaitable, Callable, Generator, Generic, List, Optional

from .files import ReadableIO
from .utils import MaybeCoro, StrBytes, T, make_awaitable

TransferUpdateCallback = Optional[Callable[["Transfer"], MaybeCoro]]


@dataclass
class Transfer(Generic[T], Awaitable[T]):
    data:      Optional[ReadableIO]   = None
    size:      Optional[int]          = None
    on_update: TransferUpdateCallback = None
    task:      Optional[Awaitable[T]] = None

    started_at:    datetime           = field(init=False)
    read:          int                = field(init=False)
    average_speed: float              = field(init=False)
    stopped:       bool               = field(init=False)
    done_at:       Optional[datetime] = field(init=False)

    _paused:          bool           = field(init=False)
    _last_read_sizes: List[int]      = field(init=False)
    _updater:         asyncio.Future = field(init=False)


    def __post_init__(self) -> None:
        self.restart()


    def __await__(self) -> Generator[None, None, T]:
        if not self.task:
            raise RuntimeError

        return self.task.__await__()


    def __aiter__(self) -> "Transfer":
        return self


    async def __anext__(self) -> StrBytes:
        while self.paused or not self.data:
            await asyncio.sleep(0.1)

        chunk = await make_awaitable(self.data.read(4096))

        if self.stopped:
            raise StopAsyncIteration

        if not chunk:
            self.done_at = datetime.now()
            await self._call_callback()
            raise StopAsyncIteration

        self.read += len(chunk)
        self._last_read_sizes.append(len(chunk))
        await self._call_callback()
        return chunk


    def __del__(self) -> None:
        with suppress(RuntimeError):  # event loop closed, python is dying
            self._updater.cancel()


    @property
    def size_left(self) -> Optional[int]:
        return None if self.size is None else self.size - self.read


    @property
    def percent_done(self) -> Optional[float]:
        return None if self.size is None else self.read / self.size * 100


    @property
    def time_spent(self) -> timedelta:
        return (self.done_at or datetime.now()) - self.started_at


    @property
    def time_left(self) -> Optional[timedelta]:
        if self.size_left is None:
            return None

        try:
            return timedelta(seconds=self.size_left / self.average_speed)
        except (ZeroDivisionError, OverflowError):
            return None


    @property
    def paused(self) -> bool:
        return self._paused


    async def set_paused(self, paused: bool) -> None:
        self._paused = paused
        await self._call_callback()


    async def stop(self) -> "Transfer":
        self.stopped = True
        self.done_at = datetime.now()
        await self._call_callback()
        return self


    def restart(self) -> "Transfer":
        with suppress(AttributeError):
            self._updater.cancel()

        self.started_at       = datetime.now()
        self.read             = 0
        self.average_speed    = 0.0
        self.stopped          = False
        self.done_at          = None
        self._paused          = False
        self._last_read_sizes = []
        self._updater         = asyncio.ensure_future(self._update_loop())

        return self


    async def _update_loop(self) -> None:
        """Calculate and update the average transfer speed every second."""

        updates = 0

        while not self.done_at:
            bytes_read_this_second = sum(self._last_read_sizes)
            self._last_read_sizes.clear()

            past_seconds_considered = min(updates or 1, 10)

            self.average_speed = max(
                0,
                self.average_speed *
                (past_seconds_considered - 1) / past_seconds_considered +
                bytes_read_this_second / past_seconds_considered,
            )

            if bytes_read_this_second:
                updates += 1

            await self._call_callback()
            await asyncio.sleep(1)

        if not updates:
            # Operation ended before we even got time to calculate avg. speed
            self.average_speed = self.read
            await self._call_callback()


    async def _call_callback(self) -> None:
        if self.on_update:
            await make_awaitable(self.on_update(self))
