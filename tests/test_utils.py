import sys

from mio.core.utils import FS_BAD_CHARS, fs_encode
from pytest import mark

pytestmark = mark.asyncio


def test_fs_encode():
    normal_chars = "".join(
        chr(i) for i in range(sys.maxunicode) if chr(i) not in FS_BAD_CHARS
    )
    assert fs_encode(normal_chars) == normal_chars
    assert fs_encode(FS_BAD_CHARS) == "%22%25%2A%2F%3A%3C%3E%3F%5C%7C"
