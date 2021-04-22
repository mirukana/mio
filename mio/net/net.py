import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from aiohttp import ClientResponseError, ClientSession
from yarl import URL

from ..core.data import Parent, Runtime
from ..core.utils import DictS, get_logger
from ..module import ClientModule
from .errors import ServerError
from .exchange import Reply, ReqData, Request

if TYPE_CHECKING:
    from ..client import Client

MethHeaders = Optional[DictS]

LOG = get_logger()


@dataclass
class Network(ClientModule):
    client: Parent["Client"] = field(repr=False)

    ping: float = field(init=False, default=0)  # in seconds

    _session: Runtime[ClientSession] = field(
        init=False, repr=False, default_factory=ClientSession,
    )


    @property
    def api(self) -> URL:
        return URL(self.client.server) / "_matrix" / "client" / "r0"


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


    async def send(self, request: Request) -> Reply:
        user_id = self.client.user_id
        token   = self.client.access_token

        if token:
            request.headers["Authorization"] = f"Bearer {token}"

        start = time.time()

        resp = await self._session.request(
            method  = request.method,
            url     = str(request.url),
            data    = None if isinstance(request.data, dict) else request.data,
            json    = request.data if isinstance(request.data, dict) else None,
            headers = request.headers,
        )

        self.ping = time.time() - start

        mime = resp.content_type
        disp = resp.content_disposition

        reply = Reply(
            status   = resp.status,
            data     = resp.content,
            json     = await resp.json() if mime == "application/json" else {},
            mime     = mime,
            size     = resp.content_length,
            filename = disp.filename if disp else None,
        )

        who = str(user_id) if user_id else None
        LOG.debug("%r\n→ %r\n← %r\n", who, request, reply, stacklevel=3)

        try:
            resp.raise_for_status()
            return reply
        except ClientResponseError:
            raise ServerError.from_reply(request, reply)


    async def disconnect(self) -> None:
        await self._session.close()
