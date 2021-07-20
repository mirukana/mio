# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

import html as html_lib

from bs4.element import Tag
from markdownify import MarkdownConverter


class HTML2Markdown(MarkdownConverter):
    def convert_a(self, el: Tag, text: str, convert_as_inline: bool) -> str:
        markdown = super().convert_a(el, text, convert_as_inline)

        if markdown == f"<{text}>":
            return text

        return markdown


def html2markdown(html: str) -> str:
    return HTML2Markdown(heading_style="ATX").convert(html).rstrip()


def plain2html(text: str) -> str:
    new = html_lib.escape(text)
    return new.replace("\n", "<br>").replace("\t", "&nbsp;" * 4)
