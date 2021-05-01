# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from io import BytesIO
from pathlib import Path

import aiofiles
from mio.client import Client
from mio.core.ids import MXC
from mio.rooms.contents.messages import (
    THUMBNAIL_POSSIBLE_PIL_FORMATS, THUMBNAIL_SIZE_MAX_OF_ORIGINAL, Audio,
    Emote, EncryptedFile, File, Image, Media, Notice, Text, Thumbnailable,
    Video,
)
from mio.rooms.room import Room
from PIL import Image as PILImage
from pytest import mark, raises

pytestmark = mark.asyncio

def create_encrypted_file(**init_kwargs):
    return EncryptedFile(**{
        "mxc":             MXC("mxc://a/b"),
        "counter_block":   "",
        "key":             "",
        "hashes":          {},
        "key_operations":  ["encrypt", "decrypt"],
        "key_type":        "oct",
        "key_algorithm":   "A256CTR",
        "key_extractable": True,
        "version":         "v2",
        **init_kwargs,
    })


def check_no_thumbnail(media_event: Thumbnailable):
    assert media_event.thumbnail_mxc is None
    assert media_event.thumbnail_encrypted is None
    assert media_event.thumbnail_width is None
    assert media_event.thumbnail_height is None
    assert media_event.thumbnail_mime is None
    assert media_event.thumbnail_size is None


async def test_textual_from_html(room: Room):
    for kind in (Text, Emote, Notice):
        await room.timeline.send(kind.from_html("<p>abc</p>"))
        await room.client.sync.once()

        content = room.timeline[-1].content
        assert isinstance(content, kind)
        assert content.body == "abc"
        assert content.format == "org.matrix.custom.html"
        assert content.formatted_body == "<p>abc</p>"


def test_textual_from_html_manual_plaintext():
    text = Text.from_html("<p>abc</p>", plaintext="123")
    assert text.body == "123"
    assert text.format == "org.matrix.custom.html"
    assert text.formatted_body == "<p>abc</p>"


def test_textual_same_html_plaintext():
    text = Text.from_html("abc", plaintext="abc")
    assert text.body == "abc"
    assert text.format is None
    assert text.formatted_body is None


def test_encrypted_file_init():
    create_encrypted_file(key_operations=["encrypt", "decrypt"])

    with raises(TypeError):
        create_encrypted_file(key_operations=["encrypt"])

    with raises(TypeError):
        create_encrypted_file(key_operations=["decrypt"])


def test_media_init():
    Media(body="", mxc=MXC("mxc://a/b"))
    Media(body="", encrypted=create_encrypted_file())

    with raises(TypeError):
        Media(body="")


async def test_generic_file_from_path(alice: Client, utf8_file: Path):
    file = await Media.from_path(alice, utf8_file)
    assert isinstance(file, File)

    assert file.body == file.filename == "utf8"
    assert file.mxc and await alice.media.download(file.mxc)
    assert file.encrypted is None
    assert file.mime == "text/plain"
    assert file.size == 15

    check_no_thumbnail(file)


async def test_image_from_path(alice: Client, large_image: Path):
    image = await Media.from_path(alice, large_image)
    assert isinstance(image, Image)

    assert image.mxc and await alice.media.download(image.mxc)
    assert image.body == "1024x768-blue.png"
    assert image.encrypted is None
    assert image.mime == "image/png"
    assert image.size == 219

    assert image.thumbnail_mxc
    assert await alice.media.download(image.thumbnail_mxc)
    assert image.thumbnail_encrypted is None
    assert image.thumbnail_width == 800
    assert image.thumbnail_height == 600
    assert image.thumbnail_mime == "image/png"
    assert image.thumbnail_size and image.thumbnail_size < image.size


async def test_video_from_path(alice: Client, mkv: Path):
    video = await Media.from_path(alice, mkv)
    assert isinstance(video, Video)

    assert video.body == "unequal-track-lengths.mkv"
    assert video.mxc and await alice.media.download(video.mxc)
    assert video.encrypted is None
    assert video.mime == "video/x-matroska"
    assert video.size == 14_196

    check_no_thumbnail(video)


async def test_audio_from_path(alice: Client, ogg: Path):
    audio = await Media.from_path(alice, ogg)
    assert isinstance(audio, Audio)

    assert audio.body == "noise.ogg"
    assert audio.mxc and await alice.media.download(audio.mxc)
    assert audio.encrypted is None
    assert audio.mime == "audio/ogg"
    assert audio.size == 10_071


async def test_unthumbnailable_formats(alice: Client):
    thumb = Thumbnailable(body="", mxc=MXC("mxc://a/b"))
    assert not await thumb._set_thumbnail(alice, BytesIO(), "text/plain")
    assert not await thumb._set_thumbnail(alice, BytesIO(), "image/svg+xml")


async def test_thumb_dimensions(alice: Client, image: Path, large_image: Path):
    thumb = Thumbnailable(body="", mxc=MXC("mxc://a/b"))

    async with aiofiles.open(image, "rb") as file:
        data = await thumb._set_thumbnail(alice, file, "image/bmp")
        assert data
        assert PILImage.open(BytesIO(data)).size == (1, 1)  # unchanged

    async with aiofiles.open(large_image, "rb") as file:
        data = await thumb._set_thumbnail(alice, file, "image/png")
        assert data
        assert PILImage.open(BytesIO(data)).size == (800, 600)  # downscaled


async def test_thumb_jpg_vs_png(
    alice:                 Client,
    gradient:              Path,
    gradient_transparency: Path,
    large_image:           Path,
):
    def png_size(image: Path) -> int:
        buffer = BytesIO()
        PILImage.open(image).save(buffer, "PNG", optimize=True)
        return len(buffer.getvalue())

    def jpg_size(image: Path) -> int:
        buffer = BytesIO()
        PILImage.open(image).convert("RGB").save(
            buffer, "JPEG", optimize=True, quality=75, progressive=True,
        )
        return len(buffer.getvalue())

    assert png_size(gradient) > jpg_size(gradient)
    assert png_size(gradient_transparency) > jpg_size(gradient_transparency)
    assert png_size(large_image) < jpg_size(large_image)

    thumb = Thumbnailable(body="", mxc=MXC("mxc://a/b"))

    async with aiofiles.open(gradient, "rb") as file:
        data = await thumb._set_thumbnail(alice, file, "image/png")
        assert data
        assert PILImage.open(BytesIO(data)).format == "JPEG"

    async with aiofiles.open(gradient_transparency, "rb") as file:
        # needed to not have data be None
        buffer = BytesIO(await file.read())
        out = BytesIO()
        PILImage.open(buffer).resize((1024, 768)).save(out, "PNG")
        out.seek(0)

        data = await thumb._set_thumbnail(alice, out, "image/png")
        assert data
        assert PILImage.open(BytesIO(data)).format == "PNG"

    async with aiofiles.open(large_image, "rb") as file:
        data = await thumb._set_thumbnail(alice, file, "image/png")
        assert data
        assert PILImage.open(BytesIO(data)).format == "PNG"


async def test_thumb_not_enough_saved_space(alice: Client, image: Path):
    thumb   = Thumbnailable(body="", mxc=MXC("mxc://a/b"))
    formats = THUMBNAIL_POSSIBLE_PIL_FORMATS

    # Not enough space saved, but original image is in an unacceptable format

    assert PILImage.open(image).format not in formats

    async with aiofiles.open(image, "rb") as file:
        data = await thumb._set_thumbnail(alice, file, "image/bmp")

    assert data
    assert len(data) > len(image.read_bytes()) * THUMBNAIL_SIZE_MAX_OF_ORIGINAL

    # Not enough space saved

    assert "PNG" in formats
    buffer = BytesIO()
    PILImage.open(image).save(buffer, "PNG", optimize=True)
    buffer.seek(0)
    assert not await thumb._set_thumbnail(alice, buffer, "image/png")
