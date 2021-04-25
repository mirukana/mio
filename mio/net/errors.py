import textwrap
from dataclasses import dataclass
from enum import IntEnum
from http import HTTPStatus
from typing import TYPE_CHECKING, ClassVar, Optional

from ..core.data import Runtime
from ..core.errors import MioError

if TYPE_CHECKING:
    from .exchange import Reply


class NonStandardRetriableStatus(IntEnum):
    PROXY_TIMEOUT     = (598, "Network read timeout error behind proxy")
    UNKNOWN_ERROR     = (520, "Origin returned unknown response to Cloudflare")
    SERVER_DOWN       = (521, "Origin refused connection from Cloudflare")
    TIMEOUT           = (522, "Cloudflare timed out contacting origin")
    UNREACHABLE       = (523, "Cloudflare could not reach origin server")
    HTTP_TIMEOUT      = (524, "Cloudflare connected via TCP but not HTTP")
    HANDSHAKE_FAIL    = (525, "Cloudflare could not SSL handshake the origin")
    INVALID_SSL_CERT  = (526, "Cloudflare got bad SSL certificate from origin")
    RAILGUN_INTERRUPT = (527, "Failure between Cloudflare and Railgun server")

    def __new__(cls, code: int, phrase: str, description: str = ""):
        # Do the same thing HTTPStatus's __new__ does
        obj             = int.__new__(cls, code)
        obj._value_     = code         # type: ignore
        obj.phrase      = phrase       # type: ignore
        obj.description = description  # type: ignore
        return obj


RETRIABLE_STATUS = {
    HTTPStatus.REQUEST_TIMEOUT,
    HTTPStatus.TOO_MANY_REQUESTS,
    HTTPStatus.INTERNAL_SERVER_ERROR,
    HTTPStatus.BAD_GATEWAY,
    HTTPStatus.SERVICE_UNAVAILABLE,
    HTTPStatus.GATEWAY_TIMEOUT,
    *NonStandardRetriableStatus,
}


@dataclass
class ServerError(MioError):
    expected_status:  ClassVar[Runtime[Optional[int]]] = None

    reply: "Reply"


    @classmethod
    def from_reply(cls, reply: "Reply") -> "ServerError":
        if "errcode" in (reply.json or {}):
            message = reply.json.get("error") or ""
            return MatrixError(reply, reply.json["errcode"], message)

        for sub in cls.__subclasses__():
            if sub.expected_status and reply.status == sub.expected_status:
                return sub(reply)

        return cls(reply)


    def __str__(self) -> str:
        reply = textwrap.indent(str(self.reply), " " * 4)
        return "%s\n%s" % (type(self).__name__, reply)


    @property
    def can_retry(self) -> bool:
        return self.reply.status in RETRIABLE_STATUS


@dataclass
class RangeNotSatisfiable(ServerError):
    expected_status = 416


@dataclass
class MatrixError(ServerError):
    m_code:  str
    message: str
