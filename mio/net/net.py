import asyncio
import math
import sys
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Deque, Optional

import aiohttp
import backoff
from yarl import URL

from ..core.data import Parent, Runtime
from ..core.files import AsyncReadable, Readable, read_chunked_binary
from ..core.utils import DictS, get_logger
from ..module import ClientModule
from .errors import ServerError
from .exchange import Reply, ReqData, Request

if TYPE_CHECKING:
    from ..client import Client

MethHeaders = Optional[DictS]

LOG = get_logger()


def _on_backoff(info: DictS) -> None:
    # https://github.com/litl/backoff#event-handlers
    lines  = str(sys.exc_info()[1]).splitlines()
    wait   = math.ceil(info["wait"])
    first  = f"{lines[0]} (retry {info['tries']}, next in {wait} seconds)"
    LOG.warning("\n".join((first, *lines[1:])), stacklevel=7)


def _on_giveup(info: DictS) -> None:
    lines  = str(sys.exc_info()[1]).splitlines()
    first  = f"{lines[0]} (no retry possible)"
    LOG.warning("\n".join((first, *lines[1:])), stacklevel=7)


@dataclass
class Network(ClientModule):
    client: Parent["Client"] = field(repr=False)

    ping: float = field(init=False, default=0)  # in seconds

    last_replies: Runtime[Deque[Reply]] = field(
        init=False, repr=False, default_factory=lambda: Deque(maxlen=256),
    )

    _session: Runtime[aiohttp.ClientSession] = field(
        init=False, repr=False, default_factory=aiohttp.ClientSession,
    )


    @property
    def api(self) -> URL:
        return URL(self.client.server) / "_matrix" / "client" / "r0"


    @property
    def media_api(self) -> URL:
        return URL(self.client.server) / "_matrix" / "media" / "r0"


    async def get(
        self, url: URL, data: ReqData = None, headers: MethHeaders = None,
    ) -> Reply:
        return await self.send(Request("GET", url, data, headers or {}))


    async def post(
        self, url: URL, data: ReqData = None, headers: MethHeaders = None,
    ) -> Reply:
        return await self.send(Request("POST", url, data, headers or {}))


    async def put(
        self, url: URL, data: ReqData = None, headers: MethHeaders = None,
    ) -> Reply:
        return await self.send(Request("PUT", url, data, headers or {}))


    @backoff.on_exception(
        lambda: backoff.fibo(max_value=60),
        (ServerError, TimeoutError, asyncio.TimeoutError, aiohttp.ClientError),
        giveup     = lambda e: isinstance(e, ServerError) and not e.can_retry,
        on_backoff = _on_backoff,
        on_giveup  = _on_giveup,
        logger     = None,
    )
    async def send(self, request: Request) -> Reply:
        if self.client._terminated:
            raise RuntimeError(f"{self.client} terminated, create a new one")

        request.identifier = self.client.user_id
        token              = self.client.access_token
        data               = request.data

        if token:
            request.headers["Authorization"] = f"Bearer {token}"

        if isinstance(data, (Readable, AsyncReadable)):
            data = read_chunked_binary(data)
        elif isinstance(data, dict):
            data = None

        start = time.time()

        resp = await self._session.request(
            method  = request.method,
            url     = str(request.url),
            data    = data,
            json    = request.data if isinstance(request.data, dict) else None,
            headers = request.headers,
        )

        self.ping = time.time() - start

        mime = resp.content_type
        disp = resp.content_disposition

        reply = Reply(
            request  = request,
            status   = resp.status,
            data     = resp.content,
            json     = await resp.json() if mime == "application/json" else {},
            mime     = mime,
            size     = resp.content_length,
            filename = disp.filename if disp else None,
        )

        try:
            resp.raise_for_status()
        except aiohttp.ClientResponseError:
            error       = ServerError.from_reply(reply)
            reply.error = error
            raise error
        else:
            LOG.debug("%s", reply, stacklevel=5)
            return reply
        finally:
            self.last_replies.appendleft(reply)


    async def disconnect(self) -> None:
        await self._session.close()
