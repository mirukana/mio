# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from mio.rooms.contents.messages import Emote, Notice, Text
from mio.rooms.room import Room
from pytest import mark

pytestmark = mark.asyncio


async def test_textual_from_html(room: Room):
    for kind in (Text, Emote, Notice):
        await room.timeline.send(kind.from_html("<p>abc</p>"))
        await room.client.sync.once()

        content = room.timeline[-1].content
        assert isinstance(content, kind)
        assert content.body == "abc"
        assert content.format == "org.matrix.custom.html"
        assert content.formatted_body == "<p>abc</p>"


async def test_textual_from_html_manual_plaintext():
    text = Text.from_html("<p>abc</p>", plaintext="123")
    assert text.body == "123"
    assert text.format == "org.matrix.custom.html"
    assert text.formatted_body == "<p>abc</p>"


async def test_textual_same_html_plaintext():
    text = Text.from_html("abc", plaintext="abc")
    assert text.body == "abc"
    assert text.format is None
    assert text.formatted_body is None
