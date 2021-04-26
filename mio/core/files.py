import hashlib
import mimetypes
import os
import re
import shutil
import stat
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Optional, Union
from urllib.parse import quote, unquote

import aiofiles
import filetype
from aiofiles.os import wrap as aiowrap  # type: ignore
from aiopath import AsyncPath
from binaryornot.helpers import is_binary_string

from .utils import StrBytes, make_awaitable

if sys.version_info < (3, 8):
    import pyfastcopy  # noqa
    from typing_extensions import Protocol, runtime_checkable
else:
    from typing import Protocol, runtime_checkable

ReadableIO = Union["Readable", "AsyncReadable"]
SeekableIO = Union["Seekable", "AsyncSeekable"]
IOChunks   = AsyncIterator[StrBytes]

# XXX: SVG could begin with big comment spanning more than size of first chunk
SVG_REGEX = re.compile(
    r"^\s*(?:<\?xml\b[^>]*>[^<]*)?"
    r"(?:<!--.*?-->[^<]*)*"
    r"(?:<svg|<!DOCTYPE svg)\b",
    re.DOTALL,
)

# Characters that can't be in file/dir names on either windows, mac or linux -
# Actual % must be encoded too to not conflict with % encoded chars
FS_BAD_CHARS: str = r'"%*/:<>?\|'

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


async def read_chunked(data: ReadableIO) -> IOChunks:
    async with rewind(data):
        while True:
            chunk = await make_awaitable(data.read(4096))
            if not chunk:
                break
            yield chunk


async def read_chunked_binary(data: ReadableIO) -> AsyncIterator[bytes]:
    async for chunk in read_chunked(data):
        yield chunk.encode() if isinstance(chunk, str) else chunk


async def guess_mime(data: ReadableIO, filename: Optional[str] = None) -> str:
    try:
        chunk1 = await read_chunked(data).__anext__()
    except StopAsyncIteration:
        return "inode/x-empty"

    guess_chunk = chunk1.encode() if isinstance(chunk1, str) else chunk1
    mime        = filetype.guess_mime(guess_chunk)

    if mime is None and filename:
        mime = mimetypes.guess_type(filename)[0]

    if mime is None and isinstance(chunk1, str):
        if SVG_REGEX.match(chunk1):
            return "image/svg+xml"
        return "text/plain"

    if mime is None:
        return "application/octet-stream"

    return mime


async def is_probably_binary(path: Union[Path, str]) -> bool:
    async with aiofiles.open(path, "rb") as file:
        return is_binary_string(await file.read(1024))


async def sha256_chunked(data: ReadableIO) -> str:
    sha256 = hashlib.sha256()

    async for chunk in read_chunked_binary(data):
        sha256.update(chunk)

    return sha256.hexdigest()
