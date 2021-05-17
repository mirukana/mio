# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

import re
from dataclasses import dataclass
from typing import Optional, Type

from yarl import URL

MXC = URL


@dataclass
class InvalidId(TypeError):
    type:            Type["_Identifier"]
    expected_format: str
    max_length:      int
    got_value:       str


class _Identifier(str):
    sigil           = r"one character, set me in subclasses"
    localpart_regex = r"[^:]+"
    server_regex    = r"[a-zA-Z\d.:-]*[a-zA-Z\d]"


    def __new__(cls, content: str) -> "_Identifier":
        if not re.match(cls.regex(), content) or len(content) > 255:
            raise InvalidId(cls, cls.regex(), 255, content)

        return str.__new__(cls, content)


    def __repr__(self) -> str:
        return "%s%r" % (self.sigil, str(self))


    @classmethod
    def regex(cls) -> str:
        sigil = re.escape(cls.sigil)
        return rf"^{sigil}{cls.localpart_regex}(:{cls.server_regex})?$"


    @property
    def localpart(self) -> str:
        return self.split(":")[0][1:]


    @property
    def server(self) -> Optional[str]:
        if ":" not in self:
            return None
        return self.split(":", maxsplit=1)[1]


class _DomainIdentifier(_Identifier):
    @classmethod
    def regex(cls) -> str:
        sigil = re.escape(cls.sigil)
        return rf"^{sigil}{cls.localpart_regex}:{cls.server_regex}"


    @property
    def server(self) -> str:
        return self.split(":", maxsplit=1)[1]


class GroupId(_DomainIdentifier):
    sigil           = "+"
    localpart_regex = r"[a-z\d._=/-]+"


class RoomId(_DomainIdentifier):
    sigil = "!"


class RoomAlias(_DomainIdentifier):
    sigil = "#"


class UserId(_DomainIdentifier):
    sigil           = "@"
    localpart_regex = r"[\x21-\x39\x3B-\x7E]+"


class EventId(_Identifier):
    sigil = "$"
