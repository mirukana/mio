import os
from pathlib import Path
from typing import List

import aiofiles
from mio.client import Client
from mio.core.ids import MXC
from mio.core.transfer import Transfer
from mio.media.file import Media
from pytest import mark

pytestmark = mark.asyncio


async def test_up_download_path(alice: Client, image: Path, tmp_path: Path):
    got:  List[Transfer[Media]] = []
    got2: List[Transfer[Media]] = []

    first = await alice.media.upload_from_path(image, on_update=got.append)
    assert got

    media = await alice.media.download_to_path(
        await first.last_mxc, tmp_path / "download.bmp", on_update=got2.append,
    )
    assert media.sha256 == first.sha256
    assert got2

    # Upload file who's sha256 matches one we've uploaded before

    media = await alice.media.upload_from_path(tmp_path / "download.bmp")
    assert media.sha256 == first.sha256
    assert (await media.last_mxc) == (await first.last_mxc)


async def test_upload_no_name_manual_mime(alice: Client, image: Path):
    async with aiofiles.open(image, "rb") as file:
        size  = image.stat().st_size
        media = await alice.media.upload(file, size, mime="application/fake")
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
    await media.remove()

    media = await alice.media.upload_from_path(utf8_file, binary=True)
    octet = "application/octet-stream"
    assert media._reply
    assert media._reply.request.headers["Content-Type"] == octet


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


async def test_multiple_refs(alice: Client, image: Path, image_symlink: Path):
    media1 = await alice.media.upload_from_path(image)
    media2 = await alice.media.upload_from_path(image_symlink)
    assert media1 == media2

    refs = {r.named_file.name async for r in media2.references}
    assert refs == {image.name, image_symlink.name}


async def test_named_file_clash(alice: Client, image: Path, utf8_file: Path):
    media1 = await alice.media.upload_from_path(image)

    async with aiofiles.open(utf8_file) as file:
        size   = utf8_file.stat().st_size
        media2 = await alice.media.upload(file, size, image.name)

    assert media1 != media2
    assert (await media1.last_reference).named_file.name == image.name
    assert (await media1.last_reference).server_filename == image.name

    solved_clash = image.with_suffix(f".001{image.suffix}").name
    assert (await media2.last_reference).named_file.name == solved_clash
    assert (await media2.last_reference).server_filename == image.name


async def test_adding_existing_ref(alice: Client, image: Path):
    media = await alice.media.upload_from_path(image)
    assert len([r async for r in media.references]) == 1

    added = await media.add_reference(await media.last_mxc)
    assert len([r async for r in media.references]) == 1
    assert await media.last_reference == added


async def test_removing_non_existent_ref(alice: Client, image: Path):
    media = await alice.media.upload_from_path(image)
    assert len([r async for r in media.references]) == 1

    removed = await media.remove_reference(MXC("mxc://fake/fake"))
    assert removed is None
    assert len([r async for r in media.references]) == 1
