# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

import sys
from io import BytesIO, StringIO
from pathlib import Path

import aiofiles
from mio.core.files import (
    FS_BAD_CHARS, encode_name, guess_mime, sha256_chunked,
)
from pytest import mark

pytestmark = mark.asyncio


async def test_encode_name():
    normal_chars = "".join(
        chr(i) for i in range(sys.maxunicode) if chr(i) not in FS_BAD_CHARS
    )
    assert encode_name(normal_chars) == normal_chars
    assert encode_name(FS_BAD_CHARS) == "%22%25%2A%2F%3A%3C%3E%3F%5C%7C"


async def test_guess_mime_empty():
    assert await guess_mime(BytesIO()) == "inode/x-empty"


async def test_guess_mime_from_filename():
    assert await guess_mime(BytesIO(b"abc")) == "application/octet-stream"
    assert await guess_mime(BytesIO(b"abc"), "a.png") == "image/png"


async def test_guess_mime_svg_no_filename():
    assert await guess_mime(StringIO("<svg>")) == "image/svg+xml"


async def test_sha256_binary(image: Path):
    sha = "7a76913febd4b0a0c43fa93cfd0cc6c2f037f722fc84c6ba0ddc33af2e08d558"

    async with aiofiles.open(image, "rb") as file:
        assert await sha256_chunked(file) == sha


async def test_sha256_text(utf8_file: Path):
    sha = "d2878e8a038ce6701a7c1029e2569f3d5248ff2c98aba9439f012b9bbce1b688"

    async with aiofiles.open(utf8_file, "rb") as file:
        assert await sha256_chunked(file) == sha


async def test_sha256_empty(utf8_file: Path):
    sha = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert await sha256_chunked(BytesIO()) == sha
