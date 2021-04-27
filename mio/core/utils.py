import logging
from contextlib import contextmanager
from inspect import isawaitable
from io import StringIO
from typing import (
    Any, Awaitable, Dict, Generator, Iterator, List, Mapping, MutableMapping,
    Optional, Tuple, Type, TypeVar, Union,
)

from rich.console import Console
from rich.logging import RichHandler
from rich.text import Text as RichText

# Characters that can't be in file/dir names on either windows, mac or linux -
# Actual % must be encoded too to not conflict with % encoded chars
FS_BAD_CHARS: str = r'"%*/:<>?\|'

StrBytes     = Union[str, bytes]
DictS        = Dict[str, Any]
NoneType     = type(None)
T            = TypeVar("T")
MaybeCoro    = Optional[Awaitable[None]]
ErrorCatcher = Union[Type[Exception], Tuple[Type[Exception], ...]]


class LogHandler(RichHandler):
    short_names = {
        "DEBUG":    "~",
        "INFO":     "i",
        "WARNING":  "!",
        "ERROR":    "X",
        "CRITICAL": "F",
    }


    def get_level_text(self, record):
        return RichText.styled(
            self.short_names[record.levelname],
            f"logging.level.{record.levelname.lower()}",
        )


logging.basicConfig(
    level    = logging.INFO,
    format   = "%(message)s\n",
    datefmt  = "%T",
    handlers = [LogHandler(
        rich_tracebacks     = True,
        omit_repeated_times = False,
        log_time_format     = "%F %T",
    )],
)


def get_logger(name: str = __name__) -> logging.Logger:
    return logging.getLogger(name)


LOG = get_logger()


def rich_repr(*objects: Any, sep: str = " ", color: bool = False) -> str:
    out = StringIO()
    Console(file=out, force_terminal=color).print(*objects, sep=sep, end=" ")
    return out.getvalue().rstrip()


def rich_thruthies(*args, sep: str = " ") -> str:
    return rich_repr(*[a for a in args if a], sep=sep)


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
    return await result if isawaitable(result) else result


@contextmanager
def report(
    *types: Type[Exception], level: int = logging.WARNING, trace: bool = False,
) -> Iterator[List[Exception]]:

    caught: List[Exception] = []

    try:
        yield caught
    except types as e:
        caught.append(e)

        if trace:
            LOG.exception("Caught exception", stacklevel=3)
        else:
            LOG.log(level, repr(e), stacklevel=3)
