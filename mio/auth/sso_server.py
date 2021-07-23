# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Generator

from aiohttp import web
from yarl import URL

if TYPE_CHECKING:
    from mio.client import Client

SUCCESS_PAGE_HTML = """<!DOCTYPE html>
<html>
    <head>
        <title>Login Success</title>
        <meta charset="utf-8">
        <style>
            body { background: hsl(0, 0%, 90%); }

            @keyframes appear {
                0% { transform: scale(0); }
                45% { transform: scale(0); }
                80% { transform: scale(1.6); }
                100% { transform: scale(1); }
            }

            .circle {
                width: 90px;
                height: 90px;
                position: absolute;
                top: 50%;
                left: 50%;
                margin: -45px 0 0 -45px;
                border-radius: 50%;
                font-size: 60px;
                line-height: 90px;
                text-align: center;
                background: hsl(203, 51%, 15%);
                color: hsl(162, 56%, 42%, 1);
                animation: appear 0.4s linear;
            }
        </style>
    </head>

    <body><div class="circle">✓</div></body>
</html>"""


@dataclass
class RequestHandler:
    server: "SSOServer"

    async def handle(self, request: web.Request) -> web.Response:
        server = self.server

        if "loginToken" in request.query:
            server.token = request.query["loginToken"]
            success_page = server.success_page_html
            return web.Response(content_type="text/html", text=success_page)

        url = server.client.net.api / "login" / "sso" / "redirect"
        raise web.HTTPFound(url % {"redirectUrl": str(server.login_url)})


class SSOServer:
    """Local HTTP server to retrieve a SSO login token.

    An instanciated server will start handling requests. Await the instance
    to wait for the login process to be completed and get an SSO token.
    The user opens `SSOServer.login_url` in a browser for the login process.
    """

    def __init__(self, client: "Client", success_page_html: str) -> None:
        self.client            = client
        self.success_page_html = success_page_html
        self.token             = ""

        self._app     = web.Application()
        self._handler = RequestHandler(self)
        self._runner  = web.AppRunner(self._app)
        self._app.add_routes([web.get("/", self._handler.handle)])

        self._task = asyncio.ensure_future(self._start())
        self._task


    @property
    def login_url(self) -> URL:
        ip, port = self._runner.addresses[0]
        return URL(f"http://{ip}:{port}")


    def __await__(self) -> Generator[None, None, str]:
        return self._task.__await__()


    async def _start(self) -> str:
        await self._runner.setup()
        await web.TCPSite(self._runner, "127.0.0.1", 0).start()

        while not self.token:
            await asyncio.sleep(0.1)

        await self._runner.cleanup()
        return self.token
