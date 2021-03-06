# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, AsyncIterator, Optional, Union

import aiofiles
from aiopath import AsyncPath

from ..core.data import Parent
from ..core.files import (
    SeekableIO, add_write_permissions, atomic_write, copy_file_with_metadata,
    decode_name, read_chunked_binary, remove_write_permissions, sha256_chunked,
)
from ..core.ids import MXC
from ..e2e.contents import EncryptedMediaInfo
from ..net.exchange import Reply
from .thumbnail import Thumbnail, ThumbnailForm, ThumbnailMode

if TYPE_CHECKING:
    from .store import MediaStore

@dataclass
class StoreMedia:
    store:  Parent["MediaStore"] = field(repr=False)
    sha256: str

    _reply: Optional[Reply] = field(
        init=False, repr=False, default=None, compare=False,
    )


    @classmethod
    async def from_data(
        cls, store: "MediaStore", data: SeekableIO,
    ) -> "StoreMedia":

        sha256 = await sha256_chunked(data)
        content = store._content_path(sha256)

        if not await content.exists():
            await content.parent.mkdir(parents=True, exist_ok=True)

            async with atomic_write(content, "wb") as output:
                async for chunk in read_chunked_binary(data):
                    await output.write(chunk)  # type: ignore

            await remove_write_permissions(content)

        return cls(store, sha256)


    @classmethod
    async def from_file_to_move(
        cls, store: "MediaStore", path: Union[Path, str],
    ) -> "StoreMedia":

        apath = AsyncPath(path)

        async with aiofiles.open(apath, "rb") as file:
            sha256 = await sha256_chunked(file)

        content = store._content_path(sha256)

        await content.parent.mkdir(parents=True, exist_ok=True)
        await apath.replace(content)
        await remove_write_permissions(content)

        return cls(store, sha256)


    @classmethod
    async def from_mxc(cls, store: "MediaStore", mxc: MXC) -> "StoreMedia":
        mxc_path = store._mxc_path(mxc)

        if not await mxc_path.exists():
            raise FileNotFoundError(mxc_path)

        return cls(store, sha256=(await mxc_path.readlink()).parent.name)


    @property
    def content(self) -> AsyncPath:
        return self.store._content_path(self.sha256)


    @property
    async def references(self) -> AsyncIterator["Reference"]:
        async for named_link in self.content.parent.glob("ref.*"):
            named_file = await named_link.readlink()
            conflict   = self.store._named_conflict_marker(named_file)
            fname      = named_file.name

            with suppress(FileNotFoundError):
                fname = (await conflict.readlink()).name

            mxc_file = await named_file.readlink()
            host     = decode_name(mxc_file.parent.parent.parent.name)
            mxc      = MXC(f"mxc://{host}/{decode_name(mxc_file.parent.name)}")
            decrypt  = self.store._decrypt_info_path(mxc)

            args = (named_link, named_file, mxc_file, decrypt, mxc, fname)
            yield Reference(self, *args)


    async def last_reference(
        self, encrypted: Optional[bool] = None,
    ) -> "Reference":
        refs = [
            r async for r in self.references
            if encrypted is None or
            (encrypted is True and await r.decrypt_file.exists()) or
            (encrypted is False and not await r.decrypt_file.exists())
        ]
        return max(refs, key = lambda r: int(r.named_link.name.split(".")[1]))


    async def last_mxc(self, encrypted: Optional[bool] = None) -> MXC:
        return (await self.last_reference(encrypted)).mxc


    async def remove(self) -> None:
        async for ref in self.references:
            await ref.remove()

        await self.content.unlink()
        await self.content.parent.rmdir()


    async def save_as(self, target: Union[Path, str]) -> "StoreMedia":
        await AsyncPath(target).parent.mkdir(parents=True, exist_ok=True)
        await copy_file_with_metadata(self.content, target)
        await add_write_permissions(target)
        return self


@dataclass
class Reference:
    media:           Parent[StoreMedia] = field(repr=False)
    named_link:      AsyncPath
    named_file:      AsyncPath
    mxc_file:        AsyncPath
    decrypt_file:    AsyncPath
    mxc:             MXC
    server_filename: str


    @classmethod
    async def create(
        cls,
        media:        StoreMedia,
        mxc:          MXC,
        filename:     Optional[str]                = None,
        decrypt_info: Optional[EncryptedMediaInfo] = None,
    ) -> "Reference":

        # MXC & decrypt info files

        assert mxc.host
        mxc_file = media.store._mxc_path(mxc)
        df = decrypt_file = media.store._decrypt_info_path(mxc)

        # Named file

        if not filename:
            filename = mxc.path[1:]

        counter      = 0
        date         = datetime.utcnow()
        named_file_0 = media.store._named_path(filename, date, counter)
        named_file   = named_file_0

        while await named_file.exists():
            counter    += 1
            named_file  = media.store._named_path(filename, date, counter)

        if counter:
            name_conflict = media.store._named_conflict_marker(named_file)
        else:
            name_conflict = None

        # Named link

        counter    = 0
        named_link = media.store._named_link(media.sha256, counter)

        while await named_link.exists():
            counter    += 1
            named_link  = media.store._named_link(media.sha256, counter)

        # Create everything

        await mxc_file.parent.mkdir(parents=True, exist_ok=True)
        await mxc_file.symlink_to(media.content)

        await named_file.parent.mkdir(parents=True, exist_ok=True)
        await named_file.symlink_to(mxc_file)
        await named_link.symlink_to(named_file)

        if name_conflict:
            await name_conflict.parent.mkdir(parents=True, exist_ok=True)
            await name_conflict.symlink_to(named_file_0)

        if decrypt_info:
            await decrypt_file.write_text(decrypt_info.json)

        return cls(media, named_link, named_file, mxc_file, df, mxc, filename)


    @property
    async def thumbnails(self) -> AsyncIterator[Thumbnail]:
        async for file in self.mxc_file.parent.glob("*x*-*"):
            size, mode    = file.name.split("-")
            width, height = size.split("x")

            form = ThumbnailForm.best_match(
                int(width), int(height), ThumbnailMode(mode),
            )

            yield Thumbnail(self.media.store, self.mxc, form)


    async def remove(self) -> None:
        await self.named_link.unlink()
        await self.named_file.unlink()
        await self.mxc_file.unlink()

        async for thumb in self.thumbnails:
            await thumb.remove()
