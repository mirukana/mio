from dataclasses import dataclass, field
from typing import Dict, Optional, Union

from aiohttp import StreamReader
from yarl import URL

from ..core.files import IOChunks, ReadableIO
from ..core.utils import DictS

ReqData = Union[None, bytes, DictS, ReadableIO, IOChunks]


@dataclass
class Request:
    method:  str
    url:     URL
    data:    ReqData        = None
    headers: Dict[str, str] = field(default_factory=dict, repr=False)


@dataclass
class Reply:
    request:  Request       = field(repr=False)
    status:   int
    data:     StreamReader  = field(repr=False)
    json:     DictS         = field(default_factory=dict)
    mime:     str           = "application/octet-stream"
    size:     Optional[int] = None
    filename: Optional[str] = None
