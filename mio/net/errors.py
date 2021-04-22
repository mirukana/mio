from dataclasses import dataclass

from ..core.errors import MioError
from .exchange import Reply, Request


@dataclass
class ServerError(MioError):
    request: Request
    reply:   Reply

    @classmethod
    def from_reply(cls, request: "Request", reply: "Reply") -> "ServerError":
        if "errcode" in reply.json:
            message = reply.json.get("error") or ""
            return MatrixError(request, reply, reply.json["errcode"], message)

        return cls(request, reply)


@dataclass
class MatrixError(ServerError):
    m_code:  str
    message: str
