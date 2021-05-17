# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from mio.core.utils import comma_and_join
from pytest import mark

pytestmark = mark.asyncio


def test_comma_and_join():
    assert comma_and_join() == ""
    assert comma_and_join("a") == "a"
    assert comma_and_join("a", "b") == "a and b"
    assert comma_and_join("a", "b", "c") == "a, b and c"
