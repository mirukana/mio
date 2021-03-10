import json
import logging as log
import traceback
from contextlib import contextmanager
from dataclasses import dataclass, field
from dataclasses import fields as get_fields
from dataclasses import is_dataclass, replace
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import (
    Any, Callable, ClassVar, Collection, Dict, ForwardRef, Generator, Iterator,
    Mapping, MutableMapping, Optional, Sequence, Tuple, Type, TypeVar, Union,
)
from uuid import UUID

import typingplus
from aiofiles import open as aiopen
from typing_extensions import Annotated, get_origin

from .errors import MioError

try:
    from devtools import debug
except ModuleNotFoundError:
    def debug(*args) -> None:
        log.error("\n".join((repr(a) for a in args)))

ErrorCatcher = Union[Type[Exception], Tuple[Type[Exception], ...]]
Converters   = Dict[Union[str, Type], Callable[[Any], Any]]
DictS        = Dict[str, Any]
T            = TypeVar("T")
KT           = TypeVar("KT")
VT           = TypeVar("VT")
JSONT        = TypeVar("JSONT", bound="JSON")
JSONFileT    = TypeVar("JSONFileT", bound="JSONFile")
_Missing     = object()
NoneType     = type(None)

_Runtime = object()
_Parent  = object()
Runtime  = Annotated[T, _Runtime]
Parent   = Annotated[T, _Runtime, _Parent]


class AsyncInit:
    def __await__(self):
        yield from self.__ainit__().__await__()
        return self

    async def __ainit__(self) -> None:
        pass


@dataclass
class Map(Mapping[KT, VT]):
    # _data field must be defined by subclasses
    def __getitem__(self, key: KT) -> VT:
        return self._data[key]  # type: ignore

    def __iter__(self) -> Iterator[KT]:
        return iter(self._data)  # type: ignore

    def __len__(self) -> int:
        return len(self._data)  # type: ignore


@dataclass
class Frozen:
    def __setattr__(self, name: str, value: Any) -> None:
        fields = self.__dataclass_fields__  # type: ignore

        if name in fields and name not in self.__dict__:
            super().__setattr__(name, value)
        else:
            raise AttributeError(f"Cannot modify frozen class {self!r}")


@dataclass
class JSONLoadError(MioError):
    error: Exception


@dataclass
class JSON:
    aliases: ClassVar[Dict[str, Union[str, Sequence[str]]]] = {}

    loaders: ClassVar[Converters] = {
        bytes: lambda v: v.encode(),
        datetime: lambda v: datetime.fromtimestamp(v / 1000),
        timedelta: lambda v: timedelta(seconds=v / 1000),
    }

    dumpers: ClassVar[Converters] = {
        UUID: str,
        Path: str,
        Enum: lambda v: v.value,
        bytes: lambda v: v.decode(),
        datetime: lambda v: v.timestamp() * 1000,
        timedelta: lambda v: v.total_seconds() * 1000,
    }


    @property
    def dict(self) -> DictS:
        data: DictS = {}

        for f in get_fields(self):
            value          = getattr(self, f.name)
            unset_optional = f.default is None and value is None
            is_classvar    = getattr(f.type, "__origin__", None) is ClassVar

            if is_classvar or annotation_is_runtime(f.type) or unset_optional:
                continue

            path = self.aliases.get(f.name, f.name)
            path = (path,) if isinstance(path, str) else path
            dct  = data

            for part in path[:-1]:
                dct = dct.setdefault(part, {})

            dct[path[-1]] = self._dump(value, f.name)

        return data


    @property
    def json(self) -> str:
        return json.dumps(self.dict, indent=4, ensure_ascii=False)


    @classmethod
    def from_dict(
        cls: Type[JSONT], data: DictS, parent: Optional["JSON"] = None,
    ) -> JSONT:

        if not isinstance(data, dict):
            raise JSONLoadError(TypeError(f"Expected dict, got {data!r}"))

        fields = {}

        for f in get_fields(cls):
            if getattr(f.type, "__origin__", None) is ClassVar:
                continue

            if parent and annotation_is_parent(f.type):
                fields[f.name] = parent
                continue

            path  = cls.aliases.get(f.name, f.name)
            path  = (path,) if isinstance(path, str) else path
            value = data

            for part in path:
                value = value.get(part, _Missing)
                if value is _Missing:
                    break

            if value is not _Missing:
                fields[f.name] = cls._load(f.type, value, f.name, parent)

        try:
            return cls(**fields)  # type: ignore
        except TypeError as e:
            raise JSONLoadError(e)


    @classmethod
    def from_json(cls: Type[JSONT], data: str, **defaults) -> JSONT:
        return cls.from_dict({**defaults, **json.loads(data)})


    def but(self, **fields) -> "JSON":
        return replace(self, **fields)


    def _dump(self, value: Any, name: Optional[str] = None) -> Any:
        # Use any dumper we that suits this value to convert it first

        if name and name in self.dumpers:
            value = self.dumpers[name](value)

        if type(value) in self.dumpers:
            value = self.dumpers[type(value)](value)

        for parent in deep_find_parent_classes(type(value)):
            if parent in self.dumpers:
                return self.dumpers[parent](value)

        # Process nested structures

        if is_dataclass(value) and is_subclass(type(value), JSON):
            return value.dict

        if is_dataclass(value):
            return {
                f.name: self._dump(getattr(value, f.name), f.name)
                for f in get_fields(value)
                if not getattr(f.type, "__origin__", None) is ClassVar and
                not annotation_is_runtime(f.type) and
                not (f.default is None and getattr(value, f.name) is None)
            }

        if isinstance(value, Mapping):
            return {
                self._dump_dict_key(k): self._dump(v) for k, v in value.items()
            }

        is_text = isinstance(value, (str, bytes))

        if isinstance(value, Collection) and not is_text:
            return [self._dump(v) for v in value]

        # Single value that has already been dumped by a suitable dumper if any

        return value


    def _dump_dict_key(self, key: Any) -> str:
        if isinstance(key, str):
            return key

        key = self._dump(key)
        if isinstance(key, str):
            return key

        return json.dumps(key, ensure_ascii=False)


    @classmethod
    def _load(
        cls,
        annotation: Any,
        value:      Any,
        field_name: Optional[str]    = None,
        parent:     Optional["JSON"] = None,
    ) -> Any:

        typ     = unwrap_annotated(annotation)
        datacls = is_dataclass(typ)
        value    = cls._apply_loader(typ, value, field_name)

        if datacls and is_subclass(typ, JSON) and isinstance(value, Mapping):
            return typ.from_dict(value)

        if datacls and isinstance(value, Mapping):
            return typ(**{
                f.name:
                    parent if parent and annotation_is_parent(f.type) else
                    cls._load(f.type, value[f.name], f.name)

                for f in get_fields(typ)
                if getattr(f.type, "__origin__", None) is not ClassVar and
                f.name in value
            })

        value = cls._auto_cast(typ, value)
        typo = getattr(typ, "__bound__", typ)
        typo = getattr(typo, "__origin__", typo)

        if typo is Union or isinstance(typo, (str, ForwardRef)):
            return value

        if is_subclass(typo, Mapping) and isinstance(value, Mapping):
            key_type, value_type = getattr(typ, "__args__", (Any, Any))
            key_type_origin      = getattr(key_type, "__origin__", key_type)

            dct = {
                cls._load(
                    key_type,
                    k if is_subclass(key_type_origin, str) else json.loads(k),
                ): cls._load(value_type, v) for k, v in value.items()
            }

            try:
                return getattr(typ, "__origin__", typ)(dct)
            except TypeError:  # happens for typing.Mapping/Dict/etc
                return dct

        if isinstance(value, (str, bytes)):
            return value

        if is_subclass(typo, Collection) and isinstance(value, Collection):
            items: Collection

            if is_subclass(typo, tuple):
                item_types = getattr(typ, "__args__", (Any, ...))
                items      = tuple(
                    cls._load(item_types[0 if ... in item_types else i], v)
                    for i, v in enumerate(value)
                )
            else:
                item_type = getattr(typ, "__args__", (Any,))[0]
                items     = [cls._load(item_type, v) for v in value]

            try:
                return getattr(typ, "__origin__", typ)(items)
            except TypeError:  # happens for typing.List/Tuple/etc
                return items

        return value


    @classmethod
    def _get_loadable_type(cls, annotation: Any, value: Any) -> Optional[Type]:
        # __bound__ is for `TypeVar`s, __origin__ for parameterized annotations
        typ = getattr(annotation, "__bound__", annotation)
        typ = getattr(typ, "__origin__", typ)

        if typ is Union:
            # Warning: Unions with exotic types requiring conversion won't
            # be handled automatically, we can't know which type to use
            choices = annotation.__args__
            if len(choices) == 2 and NoneType in choices:
                non_none = next(a for a in choices if a is not NoneType)
                typ      = NoneType if value is None else non_none
            else:
                for choice in choices:
                    if choice is Any or isinstance(value, choice):
                        typ = choice
                        break

            typ = getattr(typ, "__bound__", typ)
            typ = getattr(typ, "__origin__", typ)

        return None if isinstance(typ, (TypeVar, ForwardRef, str)) else typ


    @classmethod
    def _apply_loader(
        cls, annotation: Any, value: Any, field_name: Optional[str] = None,
    ) -> Any:

        if field_name and field_name in cls.loaders:
            with convert_errors(JSONLoadError):
                return cls.loaders[field_name](value)

        typ = cls._get_loadable_type(annotation, value)
        if not typ:
            return value

        if typ in cls.loaders:
            with convert_errors(JSONLoadError):
                return cls.loaders[typ](value)

        # This won't work for types like List, Dict, etc
        for parent in deep_find_parent_classes(typ):
            if parent in cls.loaders:
                with convert_errors(JSONLoadError):
                    return cls.loaders[parent](value)

        return value


    @classmethod
    def _auto_cast(cls, annotation: Any, value: Any) -> Any:
        typ = cls._get_loadable_type(annotation, value)

        if typ:
            with convert_errors(JSONLoadError):
                return typingplus.cast(typ, value)

        return value


@dataclass
class JSONFile(JSON, AsyncInit):
    path: Runtime[Path] = field(repr=False)


    async def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = self.json

        async with aiopen(self.path, "w") as file:
            await file.write(data)


    @classmethod
    async def load(
        cls:    Type[JSONFileT],
        path:   Path,
        parent: Optional["Parent"] = None,
    ) -> JSONFileT:

        data = {"path": path}

        if path.exists():
            async with aiopen(path) as file:
                data.update(json.loads(await file.read()))

        return await cls.from_dict(data, parent)


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


def annotation_is_runtime(ann: Any) -> bool:
    return get_origin(ann) is Annotated and _Runtime in ann.__metadata__


def annotation_is_parent(ann: Any) -> bool:
    return get_origin(ann) is Annotated and _Parent in ann.__metadata__


def unwrap_annotated(ann: Any) -> Any:
    return ann.__origin__ if get_origin(ann) is Annotated else ann


def is_subclass(value: Any, typ: Any) -> bool:
    if value is Any or typ is Any:
        return typ is value
    return issubclass(value, typ)


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


@contextmanager
def convert_errors(
    into: Callable[[Exception], Exception], types: ErrorCatcher = Exception,
) -> Iterator[None]:
    try:
        yield None
    except types as e:
        raise into(e)
