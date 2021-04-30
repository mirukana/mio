# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Tuple, Union

import aiofiles
from aiopath import AsyncPath
from yarl import URL

from ..core.data import Parent
from ..core.files import (
    SeekableIO, atomic_write, encode_name, guess_mime, measure,
)
from ..core.ids import MXC
from ..core.transfer import Transfer, TransferUpdateCallback
from ..module import ClientModule
from ..net.errors import RangeNotSatisfiable
from ..net.exchange import Reply
from .file import Media, Reference
from .thumbnail import Thumbnail, ThumbnailForm

if TYPE_CHECKING:
    from ..client import Client


@dataclass
class MediaStore(ClientModule):
    client: Parent["Client"] = field(repr=False)


    @property
    def path(self) -> AsyncPath:
        return self.client.path.parent / "media"


    def upload(
        self,
        data:      SeekableIO,
        filename:  Optional[str]          = None,
        on_update: TransferUpdateCallback = None,
    ) -> Transfer[Media, bytes]:
        # TODO: check server max allowed size

        transfer: Transfer[Media, bytes] = Transfer(data, on_update=on_update)

        async def _upload() -> Media:
            size          = await measure(data)
            transfer.size = size
            media         = await Media.from_data(self, data)

            async for ref in media.references:
                if ref.server_filename == filename:
                    # TODO: check if mxc still exists on server & is accessible
                    return media

            mime    = await guess_mime(data)
            url     = self.net.media_api / "upload"
            headers = {"Content-Type": mime, "Content-Length": str(size)}

            if filename:
                url %= {"filename": filename}

            reply = await self.net.post(url, data, headers)
            mxc   = MXC(reply.json["content_uri"])

            await Reference.create(media, mxc, filename)
            media._reply = reply
            return media

        transfer.task = asyncio.ensure_future(_upload())
        return transfer


    async def upload_from_path(
        self, path: Union[Path, str], on_update: TransferUpdateCallback = None,
    ) -> Media:

        async with aiofiles.open(path, "rb") as file:
            return await self.upload(file, Path(path).name, on_update)


    def download(
        self, mxc: MXC, on_update: TransferUpdateCallback = None,
    ) -> Transfer[Media, bytes]:

        transfer: Transfer[Media, bytes] = Transfer(on_update=on_update)

        async def _download() -> Media:
            assert mxc.host

            with suppress(FileNotFoundError):
                return await Media.from_mxc(self, mxc)

            reply, path = await self._download_file(
                self.net.media_api / "download" / mxc.host / mxc.path[1:],
                self._partial_path(mxc),
                transfer,
            )

            media        = await Media.from_file_to_move(self, path)
            media._reply = reply
            await Reference.create(media, mxc, reply.filename)
            return media

        transfer.task = asyncio.ensure_future(_download())
        return transfer


    async def download_to_path(
        self,
        mxc:       MXC,
        path:      Union[Path, str],
        on_update: TransferUpdateCallback = None,
    ) -> Media:

        return await (await self.download(mxc, on_update)).save_as(path)


    def get_thumbnail(
        self,
        for_mxc:   MXC,
        form:      ThumbnailForm,
        on_update: TransferUpdateCallback = None,
    ) -> Transfer[Thumbnail, bytes]:

        transfer: Transfer[Thumbnail, bytes] = Transfer(on_update=on_update)

        async def _get_thumb() -> Thumbnail:
            assert for_mxc.host
            host = for_mxc.host
            mxid = for_mxc.path[1:]

            thumbnail = Thumbnail(self, for_mxc, form)

            if await thumbnail.file.exists():
                return thumbnail

            reply, path = await self._download_file(
                self.net.media_api / "thumbnail" / host / mxid % {
                    "width": form.width,
                    "height": form.height,
                    "method": form.mode.value,
                },
                thumbnail._partial_file(),
                transfer,
            )

            await thumbnail._adopt_file(thumbnail._partial_file())
            return thumbnail

        transfer.task = asyncio.ensure_future(_get_thumb())
        return transfer


    def _content_path(self, sha256: str) -> AsyncPath:
        return self.path / "sha256" / sha256[:2] / sha256 / "content"


    def _mxc_path(self, mxc: MXC) -> AsyncPath:
        assert mxc.host
        host = encode_name(mxc.host)
        mxid = encode_name(mxc.path[1:])  # strip leading /
        return self.path / "mxc" / host / mxid[:2] / mxid / "original"


    def _partial_path(self, mxc: MXC) -> AsyncPath:
        assert mxc.host
        host = encode_name(mxc.host)
        mxid = encode_name(mxc.path[1:])  # strip leading /
        return self.path / "partial" / host / mxid / "original"


    def _named_path(
        self, filename: str, date: datetime, counter: int = 0,
    ) -> AsyncPath:

        fname = encode_name(filename)
        path  = self.path / "named" / date.strftime("%Y-%m-%d") / fname

        if counter:
            return path.with_stem(f"{path.stem}.{counter:03d}")

        return path


    def _named_conflict_marker(self, named_path: AsyncPath) -> AsyncPath:
        return named_path.parent / ".conflicts" / named_path.name


    def _named_link(self, sha256: str, counter: int = 0) -> AsyncPath:
        return self._content_path(sha256).parent / f"ref.{counter:03d}"


    async def _download_file(
        self, source: URL, path: AsyncPath, transfer: Transfer,
    ) -> Tuple[Reply, AsyncPath]:

        start = 0

        if await path.exists():
            start = (await path.stat()).st_size + 1
        else:
            await path.parent.mkdir(parents=True, exist_ok=True)

        try:
            headers = {"Range": f"bytes={start}-"} if start else None
            reply   = await self.net.get(source, headers)
        except RangeNotSatisfiable as e:
            return (e.reply, path)

        transfer.data = reply.data
        transfer.read = max(start - 1, 0)
        transfer.size = reply.size

        # 206 means we requested a range of bytes and the server complied
        mode = "ab" if reply.status == 206 else "wb"

        async with atomic_write(path, mode) as output:
            async for chunk in transfer:
                await output.write(chunk)

        return (reply, path)
