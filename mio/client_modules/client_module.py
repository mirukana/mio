from __future__ import annotations

from ..utils import Model


class ClientModule(Model):
    client: Client

    __repr_exclude__ = ["client"]


# Required to avoid circular import

from ..base_client import Client

ClientModule.update_forward_refs()
