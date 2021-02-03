import re
from typing import Any, ClassVar, Optional

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


class CustomString(str, CustomType):
    min_length: int                     = 0
    max_length: Optional[int]           = None
    regex:      ClassVar[Optional[str]] = None

    @classmethod
    def validate(cls, value: Any) -> "CustomString":
        if not isinstance(value, str):
            raise TypeError(f"{value!r}: must be a string")

        if len(value) < cls.min_length:
            raise TypeError(f"{value!r}: length must be >={cls.min_length}")

        if cls.max_length is not None and len(value) > cls.max_length:
            raise TypeError(f"{value!r}: length must be <={cls.max_length}")

        if cls.regex is not None and not re.match(cls.regex, value):
            raise ValueError(f"{value!r}: does not match regex {cls.regex!r}")

        return cls(value)


class EmptyString(CustomString):
    max_length = 0


class UserId(CustomString):
    max_length = 255
    regex      = rf"^@[\x21-\x39\x3B-\x7E]+:{HOST_REGEX}$"


class EventId(CustomString):
    max_length = 255
    regex      = r"^\$.+"


class RoomId(CustomString):
    max_length = 255
    regex      = rf"^!.+:{HOST_REGEX}$"


class RoomAlias(CustomString):
    regex = rf"^#.+:{HOST_REGEX}$"
