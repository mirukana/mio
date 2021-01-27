from enum import Enum
from typing import Generator, Type


class AutoStrEnum(Enum):
    """An Enum where auto() assigns the member's name instead of an integer.

    Example:
    >>> class Fruits(AutoStrEnum): apple = auto()
    >>> Fruits.apple.value
    "apple"
    """

    @staticmethod
    def _generate_next_value_(name: str, *_):
        return name


def remove_none(from_dict: dict) -> dict:
    return {k: v for k, v in from_dict.items() if v is not None}


def deep_find_subclasses(cls: Type) -> Generator[Type, None, None]:
    for subclass in cls.__subclasses__():
        yield subclass
        yield from deep_find_subclasses(subclass)
