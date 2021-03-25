import re
from typing import Any, Dict, TypeVar

from phantom.base import Phantom, Predicate
from phantom.predicates.boolean import both
from phantom.predicates.collection import count
from phantom.predicates.interval import open
from phantom.predicates.re import is_match
from yarl import URL

DictS    = Dict[str, Any]
T        = TypeVar("T")
NoneType = type(None)

HOST_REGEX    = r"[a-zA-Z\d.:-]*[a-zA-Z\d]"
USER_ID_REGEX = rf"^@[\x21-\x39\x3B-\x7E]+:{HOST_REGEX}$"

MXC = URL


def match(regex: str) -> Predicate:
    return is_match(re.compile(regex))


def match_255(regex: str) -> Predicate:
    return both(count(open(0, 255)), is_match(re.compile(regex)))


class UserId(str, Phantom, predicate=match_255(USER_ID_REGEX)):
    pass


class EventId(str, Phantom, predicate=match_255(r"^\$.+")):
    pass


class RoomId(str, Phantom, predicate=match_255(rf"^!.+:{HOST_REGEX}$")):
    pass


class RoomAlias(str, Phantom, predicate=match_255(rf"^#.+:{HOST_REGEX}$")):
    pass
