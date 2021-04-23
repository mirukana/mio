from dataclasses import dataclass
from typing import ClassVar, Optional

from ..core.data import Runtime
from ..core.errors import MioError
from .exchange import Reply


@dataclass
class ServerError(MioError):
    expected_status: ClassVar[Runtime[Optional[int]]] = None

    reply: Reply


    @classmethod
    def from_reply(cls, reply: "Reply") -> "ServerError":
        if "errcode" in reply.json:
            message = reply.json.get("error") or ""
            return MatrixError(reply, reply.json["errcode"], message)

        for sub in cls.__subclasses__():
            if sub.expected_status and reply.status == sub.expected_status:
                return sub(reply)

        return cls(reply)


@dataclass
class RangeNotSatisfiable(ServerError):
    expected_status = 416


@dataclass
class MatrixError(ServerError):
    m_code:  str
    message: str
