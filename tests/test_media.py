# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

import os
from pathlib import Path
from typing import List

import aiofiles
from mio.client import Client
from mio.core.transfer import Transfer
from mio.media.file import Media
from mio.media.thumbnail import ThumbnailForm, ThumbnailMode
from pytest import mark

pytestmark = mark.asyncio


async def test_up_download_path(alice: Client, image: Path, tmp_path: Path):
    got:  List[Transfer[Media]] = []
    got2: List[Transfer[Media]] = []

    first = await alice.media.upload_from_path(image, on_update=got.append)
    assert got
    assert first._reply
    assert first._reply.request.headers["Content-Type"] == "image/bmp"
    assert first._reply.request.headers["Content-Length"] == "58"

    media = await alice.media.download_to_path(
        await first.last_mxc, tmp_path / "download.bmp", on_update=got2.append,
    )
    assert media.sha256 == first.sha256
    assert got2

    # "Upload" file who's sha256 matches one we've uploaded before

    media = await alice.media.upload_from_path(tmp_path / "download.bmp")
    assert media.sha256 == first.sha256
    assert (await media.last_mxc) == (await first.last_mxc)


async def test_upload_no_name_manual_mime(alice: Client, image: Path):
    async with aiofiles.open(image, "rb") as file:
        media = await alice.media.upload(file, mime="application/fake")
        mxc   = await media.last_mxc
        await media.remove()
        assert not await media.content.exists()

    media = await alice.media.download(mxc)
    assert media._reply and media._reply.mime == "application/fake"
    ref = await media.last_reference
    assert ref.named_file.name == ref.mxc.path[1:]


async def test_upload_manual_binary(alice: Client, utf8_file: Path):
    media = await alice.media.upload_from_path(utf8_file)
    assert media._reply
    assert media._reply.request.headers["Content-Type"] == "text/plain"
    assert media._reply.request.headers["Content-Length"] == "15"
    await media.remove()

    media = await alice.media.upload_from_path(utf8_file, binary=True)
    octet = "application/octet-stream"
    assert media._reply
    assert media._reply.request.headers["Content-Type"] == octet
    assert media._reply.request.headers["Content-Length"] == "15"


async def test_partial_download(alice: Client, image: Path):
    # FIXME: looks like our local synapse doesn't support HTTP range headers;
    # this ends up only testing "we want a range but server doesn't comply"

    media     = await alice.media.upload_from_path(image)
    mxc       = await media.last_mxc
    partial   = alice.media._partial_path(mxc)
    full_size = (await media.content.stat()).st_size
    await media.save_as(partial)
    await media.remove()

    async with aiofiles.open(partial, "rb+") as file:
        await file.seek(-1, os.SEEK_END)
        await file.truncate()

    assert (await partial.stat()).st_size == full_size - 1

    media2 = await alice.media.download(mxc)
    assert not await partial.exists()
    assert (await media2.content.stat()).st_size == full_size

    # Full file left in the partial dir (server will raise 416 for byte range)

    await media2.save_as(partial)
    await media2.remove()
    assert (await partial.stat()).st_size == full_size

    await alice.media.download(mxc)
    assert not await partial.exists()


async def test_get_thumbnail(alice: Client, large_image: Path):
    media = await alice.media.upload_from_path(large_image)
    ref   = await media.last_reference
    assert not [t async for t in ref.thumbnails]

    form  = ThumbnailForm.tiny
    thumb = await alice.media.get_thumbnail(await media.last_mxc, form)
    assert len([t async for t in ref.thumbnails]) == 1

    assert await thumb.file.exists()
    assert thumb.for_mxc == await media.last_mxc
    assert thumb.form is form
    assert not await thumb._partial_file().exists()

    thumb2 = await alice.media.get_thumbnail(await media.last_mxc, form)
    assert thumb2.file == thumb.file
    assert len([t async for t in ref.thumbnails]) == 1

    await thumb.remove()
    assert not await thumb.file.exists()


async def test_thumbnail_best_match():
    scale = ThumbnailMode.scale
    crop  = ThumbnailMode.crop

    assert ThumbnailForm.best_match(1024, 768) is ThumbnailForm.huge
    assert ThumbnailForm.best_match(1024, 768, scale) is ThumbnailForm.huge
    assert ThumbnailForm.best_match(1024, 768, crop) is ThumbnailForm.small
    assert ThumbnailForm.best_match(900, 1) is ThumbnailForm.huge
    assert ThumbnailForm.best_match(1, 600) is ThumbnailForm.huge
    assert ThumbnailForm.best_match(799, 599) is ThumbnailForm.large
    assert ThumbnailForm.best_match(320, 240) is ThumbnailForm.medium
    assert ThumbnailForm.best_match(96, 96) is ThumbnailForm.small
    assert ThumbnailForm.best_match(96, 96, scale) is ThumbnailForm.medium
    assert ThumbnailForm.best_match(32, 32) is ThumbnailForm.tiny
    assert ThumbnailForm.best_match(1, 1, crop) is ThumbnailForm.tiny
    assert ThumbnailForm.best_match(1, 1, scale) is ThumbnailForm.medium


async def test_multiple_refs(alice: Client, image: Path, image_symlink: Path):
    media1 = await alice.media.upload_from_path(image)
    media2 = await alice.media.upload_from_path(image_symlink)
    assert media1 == media2

    refs = {r.named_file.name async for r in media2.references}
    assert refs == {image.name, image_symlink.name}


async def test_named_file_clash(alice: Client, image: Path, utf8_file: Path):
    media1 = await alice.media.upload_from_path(image)

    async with aiofiles.open(utf8_file) as file:
        media2 = await alice.media.upload(file, image.name)

    assert media1 != media2
    assert (await media1.last_reference).named_file.name == image.name
    assert (await media1.last_reference).server_filename == image.name

    solved_clash = image.with_suffix(f".001{image.suffix}").name
    assert (await media2.last_reference).named_file.name == solved_clash
    assert (await media2.last_reference).server_filename == image.name
