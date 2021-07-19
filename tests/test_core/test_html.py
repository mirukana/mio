# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from pytest import mark

from mio.core.html import html2markdown

pytestmark = mark.asyncio


def test_html2markdown_autolinks():
    url = "http://example.com"
    assert html2markdown(f"<a href='{url}'>Example</a>") == f"[Example]({url})"
    assert html2markdown(f"<a href='{url}'>{url}</a>") == url
