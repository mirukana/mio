# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

import re
from inspect import isawaitable
from io import StringIO
from typing import (
    Any, Awaitable, Dict, Generator, Mapping, MutableMapping, Optional,
    Pattern, Tuple, Type, TypeVar, Union,
)

from rich.console import Console

HTML_TAGS_RE: Pattern = re.compile(r"<\/?[^>]+(>|$)")

StrBytes     = Union[str, bytes]
DictS        = Dict[str, Any]
NoneType     = type(None)
T            = TypeVar("T")
MaybeCoro    = Optional[Awaitable[None]]
ErrorCatcher = Union[Type[Exception], Tuple[Type[Exception], ...]]


def rich_repr(*objects: Any, sep: str = " ", color: bool = False) -> str:
    out     = StringIO()
    console = Console(file=out, force_terminal=color, width=80, soft_wrap=True)
    console.print(*objects, sep=sep, end=" ")
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


def comma_and_join(*items: str) -> str:
    if not items:
        return ""

    if len(items) == 1:
        return items[0]

    return "%s and %s" % (", ".join(items[:-1]), items[-1])
