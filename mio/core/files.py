# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

import hashlib
import os
import shutil
import stat
import sys
from contextlib import asynccontextmanager, contextmanager, suppress
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import IO, Any, AsyncIterator, Iterator, Union
from urllib.parse import quote, unquote

import aiofiles
from aiofiles.os import wrap as aiowrap  # type: ignore
from aiofiles.threadpool.binary import AsyncBufferedReader
from aiofiles.threadpool.text import AsyncTextIOWrapper
from aiopath import AsyncPath
from magic import Magic

from .utils import StrBytes, make_awaitable

if sys.version_info < (3, 8):
    import pyfastcopy  # noqa
    from typing_extensions import Protocol, runtime_checkable
else:
    from typing import Protocol, runtime_checkable

ReadableIO = Union["Readable", "AsyncReadable"]
SeekableIO = Union["Seekable", "AsyncSeekable"]
IOChunks   = AsyncIterator[StrBytes]

TRUNCATE_FILE_MODES = {"w", "wb", "w+", "wb+"}

# Characters that can't be in file/dir names on either windows, mac or linux -
# Actual % must be encoded too to not conflict with % encoded chars
FS_BAD_CHARS: str = r'"%*/:<>?\|'

MIME_DETECTOR: Magic = Magic(mime=True)

# https://github.com/Tinche/aiofiles/issues/61#issuecomment-794163101
copy_file               = aiowrap(shutil.copyfile)
copy_file_with_metadata = aiowrap(shutil.copy2)
decode_name             = unquote


@runtime_checkable
class Readable(Protocol):
    def read(self, size: int = -1) -> StrBytes:
        pass


@runtime_checkable
class AsyncReadable(Protocol):
    async def read(self, size: int = -1) -> StrBytes:
        pass


@runtime_checkable
class Seekable(Readable, Protocol):
    def tell(self) -> int:
        pass

    def seek(self, pos: int, whence: int = 0) -> int:
        pass


@runtime_checkable
class AsyncSeekable(AsyncReadable, Protocol):
    async def tell(self) -> int:
        pass

    async def seek(self, pos: int, whence: int = 0) -> int:
        pass


def encode_name(name: str) -> str:
    return "".join(quote(c, safe="") if c in FS_BAD_CHARS else c for c in name)


async def remove_write_permissions(path: Union[Path, str]) -> AsyncPath:
    apath   = AsyncPath(path)
    mode    = (await apath.stat()).st_mode
    ro_mask = 0o777 ^ (stat.S_IWRITE | stat.S_IWGRP | stat.S_IWOTH)
    await apath.chmod(mode & ro_mask)
    return apath


async def add_write_permissions(path: Union[Path, str]) -> AsyncPath:
    apath     = AsyncPath(path)
    mode      = (await apath.stat()).st_mode
    read_bits = stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH
    await apath.chmod(mode | (mode & read_bits) >> 1)  # Copy read → write bits
    return apath


@contextmanager
def sync_atomic_write(
    path: Union[Path, str], mode: str = "wt", **kwargs,
) -> Iterator[IO]:

    final  = Path(path)
    prefix = f".{final.stem}."
    suffix = f"{final.suffix}.partial"

    with NamedTemporaryFile(
        dir=final.parent, prefix=prefix, suffix=suffix, delete=False,
    ) as file:
        temp = Path(file.name)

    try:
        if mode not in TRUNCATE_FILE_MODES and final.exists():
            shutil.copy2(final, temp)

        with open(temp, mode, **kwargs) as out:
            yield out

        temp.replace(final)
    finally:
        with suppress(FileNotFoundError):
            temp.unlink()


@asynccontextmanager
async def atomic_write(
    path: Union[Path, str], mode: str = "wt", **kwargs,
) -> AsyncIterator[Union[AsyncTextIOWrapper, AsyncBufferedReader]]:

    final  = AsyncPath(path)
    prefix = f".{final.stem}."
    suffix = f"{final.suffix}.partial"

    with NamedTemporaryFile(
        dir=final.parent, prefix=prefix, suffix=suffix, delete=False,
    ) as file:
        temp = AsyncPath(file.name)

    try:
        if mode not in TRUNCATE_FILE_MODES and await final.exists():
            await copy_file_with_metadata(final, temp)

        async with aiofiles.open(temp, mode, **kwargs) as out:  # type: ignore
            yield out

        await temp.replace(final)
    finally:
        with suppress(FileNotFoundError):
            await temp.unlink()


@asynccontextmanager
async def rewind(data: SeekableIO) -> AsyncIterator[None]:
    initial_position = await make_awaitable(data.tell())
    try:
        yield
    finally:
        await make_awaitable(data.seek(initial_position, 0))


@asynccontextmanager
async def try_rewind(data: Any) -> AsyncIterator[None]:
    if isinstance(data, (Seekable, AsyncSeekable)):
        async with rewind(data):
            yield
    else:
        yield


async def measure(data: SeekableIO) -> int:
    async with rewind(data):
        start = await make_awaitable(data.tell())
        await make_awaitable(data.seek(0, os.SEEK_END))
        end = await make_awaitable(data.tell())
        return end - start


async def read_chunked(data: SeekableIO) -> IOChunks:
    async with rewind(data):
        while True:
            chunk = await make_awaitable(data.read(4096))
            if not chunk:
                break
            yield chunk


async def read_chunked_binary(data: SeekableIO) -> AsyncIterator[bytes]:
    async for chunk in read_chunked(data):
        yield chunk.encode() if isinstance(chunk, str) else chunk


async def guess_mime(data: SeekableIO) -> str:
    try:
        chunk1 = await read_chunked(data).__anext__()
    except StopAsyncIteration:
        return "application/x-empty"

    return MIME_DETECTOR.from_buffer(chunk1)


async def sha256_chunked(data: SeekableIO) -> str:
    sha256 = hashlib.sha256()

    async for chunk in read_chunked_binary(data):
        sha256.update(chunk)

    return sha256.hexdigest()
