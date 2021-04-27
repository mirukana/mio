from typing import Type

from mio.core.ids import (
    EventId, GroupId, InvalidId, RoomAlias, RoomId, UserId, _DomainIdentifier,
    _Identifier,
)
from pytest import mark, raises

pytestmark = mark.asyncio


def base_checks(cls: Type[_Identifier]):
    s = cls.sigil

    for value in ("a:b", f"{s}a:" + "b" * 256, f"{s}:b", f"{s}a:→.com"):
        with raises(InvalidId):
            cls(value)

    if issubclass(cls, _DomainIdentifier):
        with raises(InvalidId):
            assert cls(f"{s}a")
    else:
        assert cls(f"{s}a").localpart == "a"
        assert cls(f"{s}a").server is None

    assert cls(f"{s}x:bar:1").localpart == "x"
    assert cls(f"{s}foo:Bar").server == "Bar"
    assert cls(f"{s}foo:bar.com").server == "bar.com"
    assert cls(f"{s}foo:bar:80").server == "bar:80"
    assert cls(f"{s}foo:bar.abc.com:80").server == "bar.abc.com:80"
    assert cls(f"{s}foo:::1").server == "::1"
    assert cls(f"{s}foo:0000:0000").server == "0000:0000"


def test_user_id():
    base_checks(UserId)
    assert UserId("@Foo/!^$%123:bar").localpart == "Foo/!^$%123"

    with raises(InvalidId):
        UserId("@→:a")
    with raises(InvalidId):
        UserId("@a")


def test_group_id():
    base_checks(GroupId)
    assert GroupId("+._=-/:a").localpart == "._=-/"

    for value in ("+A:b", "+é:b", "++:b"):
        with raises(InvalidId):
            GroupId(value)


def test_simple_ids():
    for cls in (RoomId, RoomAlias, EventId):
        base_checks(cls)
