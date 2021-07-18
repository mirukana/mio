# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from io import BytesIO
from pathlib import Path

import aiofiles
from PIL import Image as PILImage
from pytest import mark, raises

from mio.client import Client
from mio.core.ids import MXC
from mio.rooms.contents.messages import (
    THUMBNAIL_POSSIBLE_PIL_FORMATS, THUMBNAIL_SIZE_MAX_OF_ORIGINAL, Audio,
    Emote, EncryptedFile, File, Image, Media, Notice, Text, Thumbnailable,
    Video,
)
from mio.rooms.room import Room

from ..conftest import TestData

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


def test_textual_no_reply_fallback():
    assert Text("plain").html_no_reply_fallback is None

    reply = Text.from_html("<mx-reply>...</mx-reply><b>foo</b>")
    assert reply.html_no_reply_fallback == "<b>foo</b>"

    not_reply = Text.from_html("<b>foo</b>")
    assert not_reply.html_no_reply_fallback == "<b>foo</b>"


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


async def test_generic_file_from_path(alice: Client, data: TestData):
    file = await Media.from_path(alice, data.utf8)
    assert isinstance(file, File)

    assert file.body == file.filename == data.utf8.name
    assert file.mxc and await alice.media.download(file.mxc)
    assert file.encrypted is None
    assert file.mime == "text/plain"
    assert file.size == data.utf8.stat().st_size

    check_no_thumbnail(file)


async def test_image_from_path(alice: Client, data: TestData):
    image = await Media.from_path(alice, data.large_unicolor_png)
    assert isinstance(image, Image)

    assert image.mxc and await alice.media.download(image.mxc)
    assert image.body == data.large_unicolor_png.name
    assert image.encrypted is None
    assert image.mime == "image/png"
    assert image.size == data.large_unicolor_png.stat().st_size

    assert image.thumbnail_mxc
    assert await alice.media.download(image.thumbnail_mxc)
    assert image.thumbnail_encrypted is None
    assert image.thumbnail_width == 800
    assert image.thumbnail_height == 600
    assert image.thumbnail_mime == "image/png"
    assert image.thumbnail_size and image.thumbnail_size < image.size


async def test_video_from_path(alice: Client, data: TestData):
    video = await Media.from_path(alice, data.unequal_track_lengths_mkv)
    assert isinstance(video, Video)

    assert video.body == data.unequal_track_lengths_mkv.name
    assert video.mxc and await alice.media.download(video.mxc)
    assert video.encrypted is None
    assert video.mime == "video/x-matroska"
    assert video.size == data.unequal_track_lengths_mkv.stat().st_size

    check_no_thumbnail(video)


async def test_audio_from_path(alice: Client, data: TestData):
    audio = await Media.from_path(alice, data.noise_ogg)
    assert isinstance(audio, Audio)

    assert audio.body == data.noise_ogg.name
    assert audio.mxc and await alice.media.download(audio.mxc)
    assert audio.encrypted is None
    assert audio.mime == "audio/ogg"
    assert audio.size == data.noise_ogg.stat().st_size


async def test_unthumbnailable_formats(alice: Client):
    thumb = Thumbnailable(body="", mxc=MXC("mxc://a/b"))
    assert not await thumb._set_thumbnail(alice, BytesIO(), "text/plain")
    assert not await thumb._set_thumbnail(alice, BytesIO(), "image/svg+xml")


async def test_thumb_dimensions(alice: Client, data: TestData):
    thumb = Thumbnailable(body="", mxc=MXC("mxc://a/b"))

    async with aiofiles.open(data.tiny_unicolor_bmp, "rb") as file:
        got = await thumb._set_thumbnail(alice, file, "image/bmp")
        assert got
        assert PILImage.open(BytesIO(got)).size == (1, 1)  # unchanged

    async with aiofiles.open(data.large_unicolor_png, "rb") as file:
        got = await thumb._set_thumbnail(alice, file, "image/png")
        assert got
        assert PILImage.open(BytesIO(got)).size == (800, 600)  # downscaled


async def test_thumb_jpg_vs_png(alice: Client, data: TestData):
    def png_len(image: Path) -> int:
        buffer = BytesIO()
        PILImage.open(image).save(buffer, "PNG", optimize=True)
        return len(buffer.getvalue())

    def jpg_len(image: Path) -> int:
        buffer = BytesIO()
        PILImage.open(image).convert("RGB").save(
            buffer, "JPEG", optimize=True, quality=75, progressive=True,
        )
        return len(buffer.getvalue())

    assert png_len(data.gradient_png) > jpg_len(data.gradient_png)
    assert png_len(data.gradient_hole_png) > jpg_len(data.gradient_hole_png)
    assert png_len(data.large_unicolor_png) < jpg_len(data.large_unicolor_png)

    thumb = Thumbnailable(body="", mxc=MXC("mxc://a/b"))

    async with aiofiles.open(data.gradient_png, "rb") as file:
        got = await thumb._set_thumbnail(alice, file, "image/png")
        assert got
        assert PILImage.open(BytesIO(got)).format == "JPEG"

    async with aiofiles.open(data.gradient_hole_png, "rb") as file:
        # needed to not have data be None
        buffer = BytesIO(await file.read())
        out    = BytesIO()
        PILImage.open(buffer).resize((1024, 768)).save(out, "PNG")
        out.seek(0)

        got = await thumb._set_thumbnail(alice, out, "image/png")
        assert got
        assert PILImage.open(BytesIO(got)).format == "PNG"

    async with aiofiles.open(data.large_unicolor_png, "rb") as file:
        got = await thumb._set_thumbnail(alice, file, "image/png")
        assert got
        assert PILImage.open(BytesIO(got)).format == "PNG"


async def test_thumb_not_enough_saved_space(alice: Client, data: TestData):
    thumb   = Thumbnailable(body="", mxc=MXC("mxc://a/b"))
    formats = THUMBNAIL_POSSIBLE_PIL_FORMATS

    # Not enough space saved, but original image is in an unacceptable format

    assert PILImage.open(data.tiny_unicolor_bmp).format not in formats

    async with aiofiles.open(data.tiny_unicolor_bmp, "rb") as file:
        got = await thumb._set_thumbnail(alice, file, "image/bmp")

    assert got
    original_size = data.tiny_unicolor_bmp.stat().st_size
    assert len(got) > original_size * THUMBNAIL_SIZE_MAX_OF_ORIGINAL

    # Not enough space saved

    assert "PNG" in formats
    buffer = BytesIO()
    PILImage.open(data.tiny_unicolor_bmp).save(buffer, "PNG", optimize=True)
    buffer.seek(0)
    assert not await thumb._set_thumbnail(alice, buffer, "image/png")
