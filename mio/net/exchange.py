from dataclasses import dataclass, field
from datetime import datetime, timedelta
from http import HTTPStatus
from typing import Any, Dict, Optional, Union

from yarl import URL

from ..core.files import IOChunks, ReadableIO, SeekableIO
from ..core.utils import DictS, rich_thruthies
from .errors import NonStandardRetriableStatus, ServerError

ReqData = Union[None, bytes, DictS, SeekableIO, IOChunks]


@dataclass
class Request:
    method:     str
    url:        URL
    data:       ReqData        = None
    headers:    Dict[str, str] = field(default_factory=dict, repr=False)
    identifier: Any            = None
    sent_at:    datetime       = field(default_factory=datetime.now)


    def __str__(self) -> str:
        start = f"? {self.identifier}\n❯" if self.identifier else "❯"
        hdrs  = {k: v for k, v in self.headers.items() if k != "Authorization"}
        return rich_thruthies(start, self.method, self.url, self.data, hdrs)


@dataclass
class Reply:
    request:     Request
    status:      int
    data:        ReadableIO            = field(repr=False)
    json:        DictS                 = field(default_factory=dict)
    mime:        str                   = "application/octet-stream"
    size:        Optional[int]         = None
    filename:    Optional[str]         = None
    error:       Optional[ServerError] = None
    received_at: datetime              = field(default_factory=datetime.now)


    def __str__(self) -> str:
        message = ""

        if self.status in set(HTTPStatus):
            message = repr(HTTPStatus(self.status).phrase)
        elif self.status in set(NonStandardRetriableStatus):
            item    = NonStandardRetriableStatus(self.status)  # type: ignore
            message = repr(item.phrase)                        # type: ignore

        return rich_thruthies(
            f"{self.request}\n❮",
            self.status,
            message,
            "" if self.mime == "application/json" else self.mime,
            self.json,
            self.size,
            self.filename,
        )


    @property
    def ping(self) -> timedelta:
        return self.received_at - self.request.sent_at
