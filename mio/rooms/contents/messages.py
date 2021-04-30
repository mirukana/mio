# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from dataclasses import dataclass
from typing import Any, ClassVar, Dict, Optional, Type, TypeVar

from ...core.contents import EventContent
from ...core.utils import HTML_TAGS_RE

TexT = TypeVar("TexT", bound="Textual")


@dataclass
class Message(EventContent):
    type = "m.room.message"

    msgtype: ClassVar[Optional[str]] = None

    body: str

    @classmethod
    def matches(cls, event: Dict[str, Any]) -> bool:
        if not cls.msgtype:
            return False

        msgtype = event.get("content", {}).get("msgtype")
        return super().matches(event) and cls.msgtype == msgtype


@dataclass
class Textual(Message):
    format:         Optional[str] = None
    formatted_body: Optional[str] = None

    @classmethod
    def from_html(cls: Type[TexT], html: str, plaintext: str = None) -> TexT:
        if plaintext is None:
            plaintext = HTML_TAGS_RE.sub("", html)

        if plaintext == html:
            return cls(plaintext)

        return cls(plaintext, "org.matrix.custom.html", html)


@dataclass
class Text(Textual):
    msgtype = "m.text"


@dataclass
class Emote(Textual):
    msgtype = "m.emote"


@dataclass
class Notice(Textual):
    msgtype = "m.notice"
