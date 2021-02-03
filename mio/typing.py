import re
from typing import Any, ClassVar

HOST_REGEX = r"[a-zA-Z\d.:-]*[a-zA-Z\d]"


class CustomType:
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, value: Any) -> "CustomType":
        raise NotImplementedError()

    def __repr__(self) -> str:
        return "%s(%s)" % (type(self).__name__, super().__repr__())


class RegexType(str, CustomType):
    regex: ClassVar[str] = r".*"

    @classmethod
    def validate(cls, value: Any) -> "RegexType":
        if not isinstance(value, str):
            raise TypeError(f"{value!r}: must be a string")

        if not re.match(cls.regex, value):
            raise ValueError(f"{value!r}: does not match regex {cls.regex!r}")

        return cls(value)


class EmptyString(RegexType):
    regex = r"^$"


class UserId(RegexType):
    regex = rf"^@[\x21-\x39\x3B-\x7E]+:{HOST_REGEX}$"


class EventId(RegexType):
    regex = r"^\$.+"


class RoomId(RegexType):
    regex = rf"^!.+:{HOST_REGEX}$"


class RoomAlias(RegexType):
    regex = rf"^#.+:{HOST_REGEX}$"
