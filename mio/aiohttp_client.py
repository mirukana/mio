import json
import logging as log
from typing import Any, Dict, List, Optional, Type, Union
from urllib.parse import quote

import aiohttp

from . import Client, ServerError


class AiohttpClient(Client):
    _session = aiohttp.ClientSession()


    async def send(
        obj:        Union[Type["AiohttpClient"], "AiohttpClient"],
        method:     str,
        path:       List[str],
        parameters: Optional[Dict[str, Any]] = None,
        data:       Optional[bytes]          = None,
        headers:    Optional[Dict[str, Any]] = None,
    ) -> bytes:

        headers     = headers or {}
        parameters  = parameters or {}
        joined_path = "/".join(quote(p, safe="") for p in path[1:])

        if hasattr(obj, "access_token"):
            headers["Authorization"] = f"Bearer {obj.access_token}"

        for key, value in parameters.items():
            if not isinstance(value, str):
                parameters[key] = json.dumps(
                    value, ensure_ascii=False, separators=(",", ":"),
                )

        response = await obj._session.request(
            method  = method,
            url     = f"{path[0]}/{joined_path}",
            params  = parameters,
            data    = data,
            headers = headers,
        )

        read = await response.read()

        log.debug(
            "Sent %s %s %r %r\n\nReceived %r\n",
            method, joined_path, parameters, data, read,
        )

        try:
            response.raise_for_status()
        except aiohttp.ClientResponseError as e:
            raise ServerError.from_response(e.status, e.message, read)  # noqa

        return read
