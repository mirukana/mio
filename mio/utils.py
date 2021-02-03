import json
from abc import ABC, abstractproperty
from enum import Enum
from pathlib import Path
from typing import (
    Any, Callable, ClassVar, Collection, Dict, Generator, List, Mapping,
    MutableMapping, Optional, Tuple, Type, TypeVar, Union,
)

from aiofiles import open as aiopen
from pydantic import BaseModel, PrivateAttr

ModelT       = TypeVar("ModelT", bound="Model")
ReprCallable = Callable[[ModelT], Optional[str]]

class Model(BaseModel):
    __repr_exclude__: ClassVar[Collection[Union[str, ReprCallable]]] = ()

    def __repr_args__(self) -> List[Tuple[Optional[str], Any]]:
        exclude = {
            e(self) if callable(e) else e for e in self.__repr_exclude__
        }
        return [(k, v) for k, v in super().__repr_args__() if k not in exclude]


class MapModel(Model, Mapping):
    _data: dict = PrivateAttr(default_factory=dict)

    def __getitem__(self, item: Any) -> Any:
        return self._data[item]

    def __iter__(self):
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return "%s(%s)" % (type(self).__name__, self._data)


class FileModel(Model, ABC):
    json_kwargs: ClassVar[Dict[str, Any]] = {}

    @abstractproperty
    def save_file(self) -> Path:
        pass

    async def _save(self) -> None:
        json_kwargs: Dict[str, Any] = {
            "exclude": set(),
            "ensure_ascii": False,
            "indent": 4,
            **self.json_kwargs,
        }
        json_kwargs["exclude"].add("json_kwargs")

        self.save_file.parent.mkdir(parents=True, exist_ok=True)
        data = self.json(**json_kwargs)

        async with aiopen(self.save_file, "w") as file:  # type: ignore
            await file.write(data)

    @staticmethod
    async def _read_json(file: Path) -> Dict[str, Any]:
        if not file.exists():
            return {}

        async with aiopen(file) as f:  # type: ignore
            return json.loads(await f.read())


class AsyncInit:
    def __await__(self):
        yield from self.__ainit__().__await__()
        return self

    async def __ainit__(self) -> None:
        pass


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
