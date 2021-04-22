from dataclasses import dataclass

from ..core.errors import MioError
from .exchange import Reply


@dataclass
class ServerError(MioError):
    reply: Reply

    @classmethod
    def from_reply(cls, reply: "Reply") -> "ServerError":
        if "errcode" in reply.json:
            message = reply.json.get("error") or ""
            return MatrixError(reply, reply.json["errcode"], message)

        return cls(reply)


@dataclass
class MatrixError(ServerError):
    m_code:  str
    message: str
