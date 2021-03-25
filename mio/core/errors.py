import json
from dataclasses import dataclass

from yarl import URL


class MioError(Exception):
    pass


@dataclass
class ServerError(MioError):
    http_code: int
    message:   str
    method:    str
    url:       URL
    data:      bytes
    reply:     bytes

    @classmethod
    def from_response(cls, reply: bytes, **kwargs) -> "ServerError":
        try:
            parsed = json.loads(reply)
        except json.JSONDecodeError:
            parsed = None

        kwargs["reply"] = reply

        if isinstance(parsed, dict) and "errcode" in parsed:
            kwargs["m_code"]  = parsed["errcode"]
            kwargs["message"] = parsed.get("error") or kwargs.get("message")
            return MatrixError(**kwargs)

        return cls(**kwargs)

    def __str__(self) -> str:
        return repr(self)


@dataclass
class MatrixError(ServerError):
    m_code: str
