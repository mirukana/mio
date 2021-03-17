import inspect
from typing import Awaitable, Callable, Dict, List, Optional, Type, Union

from .contents import EventContent
from .events import Event
from .utils import make_awaitable

EventKey     = Union[Type[Event], Type[EventContent]]
MaybeCoro    = Optional[Awaitable[None]]
CallbackList = List[Callable[["EventCallbacks", Event], MaybeCoro]]
Callbacks    = Dict[EventKey, CallbackList]


class CallbackGroup:
    async def __call__(self, caller: "EventCallbacks", event: Event) -> None:
        for attr_name in dir(self):
            attr = getattr(self, attr_name)

            if not callable(attr) or attr_name.startswith("_"):
                continue

            params = list(inspect.signature(attr).parameters.values())

            if len(params) < 2:
                continue

            ann             = params[1].annotation
            event_type      = getattr(ann, "__origin__", ann)
            content_type    = getattr(ann, "__args__", (EventContent,))[0]
            event_matches   = isinstance(event, event_type)
            content_matches = isinstance(event.content, content_type)

            if event_matches and content_matches:
                await make_awaitable(attr(caller, event))


class EventCallbacks:
    def _callbacks(self) -> Callbacks:
        return self.callbacks  # type: ignore


    def _callback_groups(self) -> List[CallbackGroup]:
        return self.callback_groups  # type: ignore


    async def __call__(self, event: Event) -> None:
        for annotation, callbacks in self._callbacks().items():
            ann_type = getattr(annotation, "__origin__", annotation)

            if issubclass(ann_type, EventContent):
                event_type   = Event
                content_type = ann_type
            else:
                event_type   = ann_type
                default      = (EventContent,)
                content_type = getattr(annotation, "__args__", default)[0]

            event_matches   = isinstance(event, event_type)
            content_matches = isinstance(event.content, content_type)

            if event_matches and content_matches:
                for cb in callbacks:
                    await make_awaitable(cb(self, event))

        for cb_group in self._callback_groups():
            await cb_group(self, event)
