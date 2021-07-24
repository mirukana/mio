# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from io import BytesIO
from pathlib import Path

import aiofiles
from PIL import Image as PILImage
from pytest import mark, raises

from mio.client import Client
from mio.core.contents import EventContent
from mio.core.html import plain2html
from mio.core.ids import MXC
from mio.e2e.contents import EncryptedMediaInfo
from mio.rooms.contents.changes import Redacted, Redaction
from mio.rooms.contents.messages import (
    HTML_FORMAT, HTML_REPLY_FALLBACK, MATRIX_TO,
    THUMBNAIL_POSSIBLE_PIL_FORMATS, THUMBNAIL_SIZE_MAX_OF_ORIGINAL, Audio,
    Emote, File, Image, Media, Notice, Sticker, Text, Thumbnailable, Video,
)
from mio.rooms.contents.settings import HistoryVisibility, JoinRules, Name
from mio.rooms.contents.users import Member, PowerLevels
from mio.rooms.events import SendStep, StateEvent, TimelineEvent
from mio.rooms.room import Room

from ..conftest import TestData

pytestmark = mark.asyncio

def create_encrypted_media_info(**init_kwargs):
    return EncryptedMediaInfo(**{
        "mxc":             MXC("mxc://a/b"),
        "init_vector":     "",
        "key":             "",
        "sha256":          "AAAA",
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
        assert content.format == HTML_FORMAT
        assert content.formatted_body == "<p>abc</p>"


def test_textual_from_html_manual_plaintext():
    text = Text.from_html("<p>abc</p>", plaintext="123")
    assert text.body == "123"
    assert text.format == HTML_FORMAT
    assert text.formatted_body == "<p>abc</p>"


def test_textual_same_html_plaintext():
    text = Text.from_html("abc", plaintext="abc")
    assert text.body == "abc"
    assert text.format is None
    assert text.formatted_body is None


def test_textual_no_reply_fallback():
    assert Text("plain").html_no_reply_fallback is None

    reply = Text.from_html("<b>foo</b>")  # from_html will strip mx-reply
    reply.formatted_body = HTML_REPLY_FALLBACK + reply.formatted_body
    assert reply.html_no_reply_fallback == "<b>foo</b>"

    not_reply = Text.from_html("<b>foo</b>")
    assert not_reply.html_no_reply_fallback == "<b>foo</b>"


async def test_textual_replying_to(room: Room):
    await room.timeline.send(Text("plain\nmsg"))
    await room.timeline.send(Text.from_html("<b>html</b><br>msg"))
    await room.state.send(Name("Test room"))
    await room.client.sync.once()
    plain, html, other = list(room.timeline.values())[-3:]

    def check_reply_attrs(first_event, reply, fallback_content, reply_content):
        assert reply.replies_to == first_event.id
        assert reply.format == HTML_FORMAT

        assert reply.formatted_body == HTML_REPLY_FALLBACK.format(
            matrix_to = MATRIX_TO,
            room_id   = room.id,
            user_id   = room.client.user_id,
            event_id  = first_event.id,
            content   = fallback_content,
        ) + reply_content

    reply = Text("nice").replying_to(plain)
    assert reply.body == f"> <{plain.sender}> plain\n> msg\n\nnice"
    check_reply_attrs(plain, reply, plain2html(plain.content.body), "nice")

    reply = Text("nice").replying_to(html)
    assert reply.body == f"> <{plain.sender}> **html**  \n> msg\n\nnice"
    check_reply_attrs(html, reply, html.content.formatted_body, "nice")

    reply = Text.from_html("<i>nice</i>").replying_to(html)
    assert reply.body == f"> <{plain.sender}> **html**  \n> msg\n\n*nice*"
    check_reply_attrs(html, reply, html.content.formatted_body, "<i>nice</i>")

    reply = Text("nice").replying_to(other)
    assert reply.body == f"> <{plain.sender}> {Name.type}\n\nnice"
    assert other.type
    check_reply_attrs(other, reply, plain2html(other.type), "nice")


def test_encrypted_media_info_init():
    create_encrypted_media_info(key_operations=["encrypt", "decrypt"])

    with raises(TypeError):
        create_encrypted_media_info(key_operations=["encrypt"])

    with raises(TypeError):
        create_encrypted_media_info(key_operations=["decrypt"])


def test_media_init():
    Media(body="", mxc=MXC("mxc://a/b"))
    Media(body="", encrypted=create_encrypted_media_info())

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


async def test_explicit_sticker_from_path(alice: Client, data: TestData):
    sticker = await Sticker.from_path(alice, data.large_unicolor_png)
    assert isinstance(sticker, Sticker)

    assert sticker.mxc and await alice.media.download(sticker.mxc)
    assert sticker.body == data.large_unicolor_png.name
    assert sticker.encrypted is None
    assert sticker.mime == "image/png"
    assert sticker.size == data.large_unicolor_png.stat().st_size

    assert sticker.thumbnail_mxc
    assert await alice.media.download(sticker.thumbnail_mxc)
    assert sticker.thumbnail_encrypted is None
    assert sticker.thumbnail_width == 800
    assert sticker.thumbnail_height == 600
    assert sticker.thumbnail_mime == "image/png"
    assert sticker.thumbnail_size and sticker.thumbnail_size < sticker.size


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
    assert not await thumb.set_thumbnail_from(alice, BytesIO(), "text/plain")
    assert not await thumb.set_thumbnail_from(
        alice, BytesIO(), "image/svg+xml",
    )


async def test_thumb_dimensions(alice: Client, data: TestData):
    thumb = Thumbnailable(body="", mxc=MXC("mxc://a/b"))

    async with aiofiles.open(data.tiny_unicolor_bmp, "rb") as file:
        got = await thumb.set_thumbnail_from(alice, file, "image/bmp")
        assert got
        assert PILImage.open(BytesIO(got)).size == (1, 1)  # unchanged

    async with aiofiles.open(data.large_unicolor_png, "rb") as file:
        got = await thumb.set_thumbnail_from(alice, file, "image/png")
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
        got = await thumb.set_thumbnail_from(alice, file, "image/png")
        assert got
        assert PILImage.open(BytesIO(got)).format == "JPEG"

    async with aiofiles.open(data.gradient_hole_png, "rb") as file:
        # needed to not have data be None
        buffer = BytesIO(await file.read())
        out    = BytesIO()
        PILImage.open(buffer).resize((1024, 768)).save(out, "PNG")
        out.seek(0)

        got = await thumb.set_thumbnail_from(alice, out, "image/png")
        assert got
        assert PILImage.open(BytesIO(got)).format == "PNG"

    async with aiofiles.open(data.large_unicolor_png, "rb") as file:
        got = await thumb.set_thumbnail_from(alice, file, "image/png")
        assert got
        assert PILImage.open(BytesIO(got)).format == "PNG"


async def test_thumb_not_enough_saved_space(alice: Client, data: TestData):
    thumb   = Thumbnailable(body="", mxc=MXC("mxc://a/b"))
    formats = THUMBNAIL_POSSIBLE_PIL_FORMATS

    # Not enough space saved, but original image is in an unacceptable format

    assert PILImage.open(data.tiny_unicolor_bmp).format not in formats

    async with aiofiles.open(data.tiny_unicolor_bmp, "rb") as file:
        got = await thumb.set_thumbnail_from(alice, file, "image/bmp")

    assert got
    original_size = data.tiny_unicolor_bmp.stat().st_size
    assert len(got) > original_size * THUMBNAIL_SIZE_MAX_OF_ORIGINAL

    # Not enough space saved

    assert "PNG" in formats
    buffer = BytesIO()
    PILImage.open(data.tiny_unicolor_bmp).save(buffer, "PNG", optimize=True)
    buffer.seek(0)
    assert not await thumb.set_thumbnail_from(alice, buffer, "image/png")


async def test_encrypted_media(e2e_room: Room, bob: Client, data: TestData):
    await bob.rooms.join(e2e_room.id)

    alice = e2e_room.client
    await alice.sync.once()
    event = await Media.from_path(alice, data.large_unicolor_png, encrypt=True)
    await e2e_room.timeline.send(event)

    await bob.sync.once()
    got = bob.rooms[e2e_room.id].timeline[-1].content
    assert got.mxc is None
    assert got.encrypted
    assert got.mime == "image/png"
    assert got.size >= 219
    assert got.width == 1024
    assert got.height == 768

    assert got.thumbnail_mxc is None
    assert got.thumbnail_encrypted
    assert got.thumbnail_mime == "image/png"
    assert got.thumbnail_size
    assert got.thumbnail_width == 800
    assert got.thumbnail_height == 600

    media          = await bob.media.download(got.encrypted)
    original_bytes = data.large_unicolor_png.read_bytes()
    assert await media.content.read_bytes() == original_bytes


async def test_timeline_redaction(e2e_room: Room):
    new = []
    cb  = lambda room, event: new.append(event)  # noqa
    e2e_room.client.rooms.callbacks[TimelineEvent].append(cb)

    # Send original message
    await e2e_room.timeline.send(Text("hi"))
    await e2e_room.client.sync.once()

    # Redact + test local echo
    await e2e_room.timeline[-1].redact("bye")
    assert isinstance(new[-2].content, Redaction)
    assert isinstance(new[-1].content, Redacted)
    assert new[-1].redacted_by == new[-2]
    await e2e_room.client.sync.once()

    # Check Redaction in timeline
    redaction = e2e_room.timeline[-1]
    assert isinstance(redaction.content, Redaction)
    assert redaction.content.reason == "bye"

    # Check message now redacted in timeline
    redacted = e2e_room.timeline[-2]
    assert isinstance(redacted.content, Redacted)
    assert redacted.redacted_by == redaction

    # Check callback results for real events
    assert isinstance(new[-2].content, Redaction)
    assert isinstance(new[-1].content, Redacted)
    assert new[2].sending == SendStep.synced


async def test_state_redaction(room: Room):
    tl_new = []
    tl_cb  = lambda room, event: tl_new.append(event)  # noqa
    room.client.rooms.callbacks[TimelineEvent].append(tl_cb)

    st_new = []
    st_cb  = lambda room, event: st_new.append(event)  # noqa
    room.client.rooms.callbacks[StateEvent].append(st_cb)

    await room.state.send(Name("123"))
    await room.client.sync.once()
    await room.state[Name].redact("bad name")  # type: ignore
    await room.client.sync.once()
    room.client.sync.next_batch = None
    await room.client.sync.once()

    redaction = room.timeline[-1]
    assert isinstance(redaction.content, Redaction)
    assert redaction.content.reason == "bad name"

    redacted = room.state[Name]
    assert isinstance(redacted, StateEvent)
    assert isinstance(redacted.content, Redacted)
    assert redacted.redacted_by == redaction

    assert isinstance(tl_new[-2].content, Redaction)
    assert isinstance(tl_new[-1].content, Redacted)
    assert isinstance(st_new[-1].content, Redacted)


async def test_state_redaction_allowed_keys(room: Room):
    async def check(send: EventContent, expect: EventContent, state_key=""):
        event_id = await room.state.send(send, state_key)
        await room.client.sync.once()

        await room.state[type(send), state_key].redact()  # type: ignore
        await room.client.sync.once()

        assert room.state[type(send), state_key].content == expect
        assert room.timeline[event_id].content == expect

    await check(
        room.state[Member, room.client.user_id].content.but(display_name="1"),
        Member(membership=Member.Kind.join),
        room.client.user_id,
    )

    send2 = JoinRules(JoinRules.Rule.private)
    await check(send2, send2)

    send3 = HistoryVisibility(HistoryVisibility.Visibility.world_readable)
    await check(send3, send3)

    send = PowerLevels(notifications={"abc": 1}, invite=80, ban=20)
    await check(send, PowerLevels(ban=20))
