import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MioError(Exception):
    debug: Any = field(init=False, repr=False, default=None)

    def __str__(self) -> str:
        return repr(self)


@dataclass(frozen=True)
class ServerError(MioError):
    http_code: int
    message:   str

    @classmethod
    def from_response(
        cls, http_code: int, message: str, content: bytes,
    ) -> "ServerError":
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return cls(http_code, message)

        if isinstance(data, dict) and "errcode" in data:
            message = data.get("error") or message
            return MatrixError(http_code, message, data["errcode"])

        return cls(http_code, message)


@dataclass(frozen=True)
class MatrixError(ServerError):
    m_code: str
