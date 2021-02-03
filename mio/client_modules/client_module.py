from __future__ import annotations

from pydantic import BaseModel


class ClientModule(BaseModel):
    client: Client


# Required to avoid circular import

from ..base_client import Client

ClientModule.update_forward_refs()
