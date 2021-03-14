import logging
from contextlib import contextmanager
from inspect import iscoroutine
from typing import (
    Generator, Iterator, Mapping, MutableMapping, Tuple, Type, Union,
)

from rich.logging import RichHandler

ErrorCatcher = Union[Type[Exception], Tuple[Type[Exception], ...]]

logging.basicConfig(
    level    = logging.INFO,
    format   = "%(message)s",
    datefmt  = "%T",
    handlers = [RichHandler(rich_tracebacks=True, log_time_format="%F %T")],
)


def get_logger(name: str = __name__) -> logging.Logger:
    return logging.getLogger(name)


LOG = get_logger()


def remove_none(from_dict: dict) -> dict:
    return {k: v for k, v in from_dict.items() if v is not None}


def deep_find_parent_classes(cls: Type) -> Generator[Type, None, None]:
    for parent in getattr(cls, "__bases__", ()):
        yield parent
        yield from deep_find_parent_classes(parent)


def deep_find_subclasses(cls: Type) -> Generator[Type, None, None]:
    for subclass in getattr(cls, "__subclasses__", lambda: ())():
        yield subclass
        yield from deep_find_subclasses(subclass)


def deep_merge_dict(dict1: MutableMapping, dict2: Mapping) -> None:
    """Recursively update `dict1` with `dict2`'s keys."""
    # https://gist.github.com/angstwad/bf22d1822c38a92ec0a9

    for k in dict2:
        if (
            k in dict1 and
            isinstance(dict1[k], Mapping) and
            isinstance(dict2[k], Mapping)
        ):
            deep_merge_dict(dict1[k], dict2[k])
        else:
            dict1[k] = dict2[k]

async def make_awaitable(result):
    return await result if iscoroutine(result) else result


@contextmanager
def log_errors(
    types: ErrorCatcher = Exception,
    level: int          = logging.WARNING,
    trace: bool         = False,
) -> Iterator[None]:
    try:
        yield None
    except types as e:
        if trace:
            LOG.exception("Caught exception", stacklevel=3)
        else:
            LOG.log(level, repr(e), stacklevel=3)
