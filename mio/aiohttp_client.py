import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import aiohttp

from . import BaseClient, ServerError


@dataclass
class AiohttpClient(BaseClient):
    def __post_init__(self) -> None:
        super().__post_init__()
        self.session = aiohttp.ClientSession()


    async def send(
        self,
        method:     str,
        path:       List[str],
        parameters: Optional[Dict[str, Any]] = None,
        data:       Optional[bytes]          = None,
        headers:    Optional[Dict[str, Any]] = None,
    ) -> bytes:

        headers    = headers or {}
        parameters = parameters or {}

        if self.auth.access_token:
            headers["Authorization"] = f"Bearer {self.auth.access_token}"

        for key, value in parameters.items():
            if not isinstance(value, str):
                parameters[key] = json.dumps(
                    value, ensure_ascii=False, separators=(",", ":"),
                )

        joined_path = "/".join(quote(p, safe="") for p in path)

        response = await self.session.request(
            method  = method,
            url     = f"{self.homeserver}/{joined_path}",
            params  = parameters,
            data    = data,
            headers = headers,
        )

        read = await response.read()

        try:
            response.raise_for_status()
        except aiohttp.ClientResponseError as e:
            raise ServerError.from_response(e.status, e.message, read)  # noqa

        return read
