import re
from typing import Any, Dict, Optional, TypeVar

from yarl import URL

DictS    = Dict[str, Any]
T        = TypeVar("T")
NoneType = type(None)

MXC = URL


class _Identifier(str):
    sigil           = r"one character, set me in subclasses"
    localpart_regex = r".+"
    server_regex    = r"[a-zA-Z\d.:-]*[a-zA-Z\d]"


    def __new__(cls, content: str) -> "_Identifier":
        if not re.match(cls.regex(), content) or len(content) > 255:
            raise TypeError(f"{content}: incorrect format or >255 characters")

        return str.__new__(cls, content)


    def __repr__(self) -> str:
        return "%s(%r)" % (type(self).__name__, str(self))


    @classmethod
    def regex(cls) -> str:
        return rf"^{cls.sigil}{cls.localpart_regex}(:{cls.server_regex})?"


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
        return rf"^{cls.sigil}{cls.localpart_regex}:{cls.server_regex}"


    @property
    def server(self) -> str:
        return self.split(":", maxsplit=1)[1]


class GroupId(_DomainIdentifier):
    sigil           = r"+"
    localpart_regex = r"[a-z\d._=/-]+"


class RoomId(_DomainIdentifier):
    sigil = r"!"


class RoomAlias(_DomainIdentifier):
    sigil = r"#"


class UserId(_DomainIdentifier):
    sigil           = r"@"
    localpart_regex = r"[\x21-\x39\x3B-\x7E]+"


class EventId(_Identifier):
    sigil = r"\$"
