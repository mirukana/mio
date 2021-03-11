import logging as log
import traceback
from contextlib import contextmanager
from typing import (
    Generator, Iterator, Mapping, MutableMapping, Tuple, Type, Union,
)

try:
    from devtools import debug
except ModuleNotFoundError:
    def debug(*args) -> None:
        log.error("\n".join((repr(a) for a in args)))

ErrorCatcher = Union[Type[Exception], Tuple[Type[Exception], ...]]


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


@contextmanager
def log_errors(
    types: ErrorCatcher = Exception, trace: bool = False,
) -> Iterator[None]:
    try:
        yield None
    except types as e:
        if trace:
            debug("%s\n" % traceback.format_exc().rstrip())
        else:
            debug(e)