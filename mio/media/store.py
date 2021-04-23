import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Union

import aiofiles
from aiopath import AsyncPath

from ..core.data import Parent
from ..core.files import (
    SeekableIO, encode_name, guess_mime, is_probably_binary, rewind,
)
from ..core.ids import MXC
from ..core.transfer import Transfer, TransferUpdateCallback
from ..module import ClientModule
from ..net.errors import RangeNotSatisfiable
from .file import Media

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
        size:      int,
        filename:  Optional[str]          = None,
        on_update: TransferUpdateCallback = None,
        mime:      Optional[str]          = None,
    ) -> Transfer[Media]:
        # TODO: check server max allowed size

        transfer: Transfer[Media] = Transfer(data, size, on_update)

        async def _upload(mime=mime) -> Media:
            media = await Media.from_data(self, data)

            async for ref in media.references:
                if ref.server_filename == filename:
                    # TODO: check if mxc still exists on server & is accessible
                    return media

            await rewind(data)

            if mime is None:
                mime = await guess_mime(data)
                await rewind(data)

            url     = self.net.media_api / "upload"
            headers = {"Content-Type": mime, "Content-Length": str(size)}

            if filename:
                url %= {"filename": filename}

            reply = await self.net.post(url, data, headers)
            mxc   = MXC(reply.json["content_uri"])

            await media.add_reference(mxc, filename)
            media._reply = reply
            return media

        transfer.task = asyncio.ensure_future(_upload())
        return transfer


    async def upload_from_path(
        self,
        path:      Union[Path, str],
        on_update: TransferUpdateCallback = None,
        mime:      Optional[str]          = None,
        binary:    Optional[bool]         = None,
    ) -> Media:

        if binary is None:
            binary = await is_probably_binary(path)

        path = Path(path)
        size = (await AsyncPath(path).stat()).st_size
        mode = "rb" if binary else "rt"

        async with aiofiles.open(path, mode) as file:  # type: ignore
            return await self.upload(file, size, path.name, on_update, mime)


    def download(
        self, mxc: MXC, on_update: TransferUpdateCallback = None,
    ) -> Transfer[Media]:

        transfer: Transfer[Media] = Transfer(on_update=on_update)

        async def _download() -> Media:
            assert mxc.host

            with suppress(FileNotFoundError):
                return await Media.from_mxc(self, mxc)

            path  = self._partial_path(mxc)
            start = 0

            if await path.exists():
                start = (await path.stat()).st_size + 1
            else:
                await path.parent.mkdir(parents=True, exist_ok=True)

            try:
                reply = await self.net.get(
                    self.net.media_api / "download" / mxc.host / mxc.path[1:],
                    headers = {"Range": f"bytes={start}-"} if start else None,
                )
            except RangeNotSatisfiable:
                media = await Media.from_file_to_move(self, path)
                await media.add_reference(mxc, reply.filename)
                return media

            transfer.data = reply.data
            transfer.read = max(start - 1, 0)
            transfer.size = reply.size

            # 206 means we requested a range of bytes and the server complied
            mode = "ab" if reply.status == 206 else "wb"

            async with aiofiles.open(path, mode) as output:  # type: ignore
                async for chunk in transfer:
                    await output.write(chunk)

            media        = await Media.from_file_to_move(self, path)
            media._reply = reply
            await media.add_reference(mxc, reply.filename)
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


    def _content_path(self, sha256: str) -> AsyncPath:
        return self.path / "sha256" / sha256[:2] / sha256 / "content"


    def _mxc_path(self, mxc: MXC) -> AsyncPath:
        assert mxc.host
        mxid = encode_name(mxc.path[1:])  # strip leading /
        return self.path / "mxc" / encode_name(mxc.host) / mxid[:2] / mxid


    def _partial_path(self, mxc: MXC) -> AsyncPath:
        assert mxc.host
        mxid = encode_name(mxc.path[1:])  # strip leading /
        return self.path / "partial" / encode_name(mxc.host) / mxid


    def _named_path(
        self, filename: str, date: datetime, counter: int = 0,
    ) -> AsyncPath:

        fname = encode_name(filename)
        path  = self.path / "named" / date.strftime("%Y-%m-%d") / fname

        if counter:
            return path.with_stem(f"{path.stem}.{counter:03d}")

        return path


    def _named_conflict_marker(self, named_path: AsyncPath) -> AsyncPath:
        return named_path.with_name(f".{named_path.name}.conflict")


    def _named_link(self, sha256: str, counter: int = 0) -> AsyncPath:
        return self._content_path(sha256).parent / f"ref.{counter:03d}"
