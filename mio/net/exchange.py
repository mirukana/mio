from dataclasses import dataclass, field
from typing import Optional, Union

from aiohttp import StreamReader
from yarl import URL

from ..core.types import DictS

ReqData = Union[None, bytes, DictS]


@dataclass
class Request:
    method:  str
    url:     URL
    data:    ReqData
    headers: DictS = field(default_factory=dict, repr=False)


@dataclass
class Reply:
    status:   int
    data:     StreamReader  = field(repr=False)
    json:     DictS         = field(default_factory=dict)
    mime:     str           = "application/octet-stream"
    size:     Optional[int] = None
    filename: Optional[str] = None
