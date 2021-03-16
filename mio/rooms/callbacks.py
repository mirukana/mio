from inspect import signature

from ..core.contents import EventContent
from ..core.events import Event
from ..core.utils import make_awaitable
from .room import Room


class CallbackGroup:
    async def __call__(self, room: Room, event: Event) -> None:
        for attr_name in dir(self):
            attr = getattr(self, attr_name)

            if not callable(attr) or attr_name.startswith("_"):
                continue

            sig    = signature(attr)
            params = list(sig.parameters.values())

            if len(params) < 2:
                continue

            ann        = params[1].annotation
            event_type = getattr(ann, "__origin__", ann)

            if not issubclass(event_type, Event):
                continue

            default      = (EventContent,)
            content_type = getattr(ann, "__args__", default)[0]

            event_matches   = isinstance(event, event_type)
            content_matches = isinstance(event.content, content_type)

            if event_matches and content_matches:
                await make_awaitable(attr(room, event))
