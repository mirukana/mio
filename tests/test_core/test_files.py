# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

import re
import sys
from io import BytesIO, StringIO
from pathlib import Path

import aiofiles
from mio.core.files import (
    FS_BAD_CHARS, atomic_write, encode_name, guess_mime, sha256_chunked,
    sync_atomic_write,
)
from pytest import mark, raises

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


async def test_atomic_write(tmp_path: Path):
    new = tmp_path / "x.json"
    assert not new.exists()

    def tmp_file_exists():
        name = re.compile(r"^\.x\..+?\.json\.partial$")
        return any(name.match(f.name) for f in tmp_path.iterdir())

    async with atomic_write(new) as out1:
        assert tmp_file_exists()
        await out1.write("abc")  # type: ignore

    assert not tmp_file_exists()
    assert new.read_text() == "abc"

    with sync_atomic_write(new) as out2:
        assert tmp_file_exists()
        out2.write("ABC")

    assert not tmp_file_exists()
    assert new.read_text() == "ABC"

    # Check that original file is unmodified when writing is interrupted

    with raises(RuntimeError):
        async with atomic_write(new) as out3:
            await out3.write("def")  # type: ignore
            raise RuntimeError

    with raises(RuntimeError):
        with sync_atomic_write(new) as out4:
            out4.write("DEF")
            raise RuntimeError

    assert not tmp_file_exists()
    assert new.read_text() == "ABC"


async def test_atomic_append(tmp_path: Path):
    new = tmp_path / "x.json"
    assert not new.exists()
    new.write_text("abc")

    async with atomic_write(new, "a") as out1:
        await out1.write("def")  # type: ignore

    with sync_atomic_write(new, "a") as out2:
        out2.write("DEF")

    assert new.read_text() == "abcdefDEF"

    # Check that original file is unmodified when writing is interrupted

    with raises(RuntimeError):
        async with atomic_write(new) as out3:
            await out3.write("ghi")  # type: ignore
            raise RuntimeError

    with raises(RuntimeError):
        with sync_atomic_write(new) as out4:
            out4.write("GHI")
            raise RuntimeError

    assert new.read_text() == "abcdefDEF"
