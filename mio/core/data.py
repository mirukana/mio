# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

import json
import sys
from dataclasses import Field, dataclass
from dataclasses import fields as get_fields
from dataclasses import is_dataclass, replace
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import (
    Any, Callable, ClassVar, Collection, Counter, Dict, ForwardRef, Iterator,
    Mapping, Optional, Sequence, Tuple, Type, TypeVar, Union,
)
from uuid import UUID, uuid4
from weakref import WeakValueDictionary

import typingplus
from aiopath import AsyncPath
from yarl import URL

from .errors import MioError
from .files import atomic_write, sync_atomic_write
from .utils import DictS, NoneType, T, deep_find_parent_classes

if sys.version_info < (3, 8):
    from typing_extensions import Literal
else:
    from typing import Literal

if sys.version_info <= (3, 9):
    from typing_extensions import Annotated, get_origin
else:
    from typing import Annotated, get_origin

Annotated = Annotated
Literal   = Literal

Loaders   = Dict[Union[str, Type], Callable[[Any, Any], Any]]
Dumpers   = Dict[Union[str, Type], Callable[["JSON", Any], Any]]
KT        = TypeVar("KT")
VT        = TypeVar("VT")
JSONT     = TypeVar("JSONT", bound="JSON")
JSONFileT = TypeVar("JSONFileT", bound="JSONFile")
_Missing  = object()

_Runtime = object()
_Parent  = object()
Runtime  = Annotated[T, _Runtime]
Parent   = Annotated[T, _Runtime, _Parent]


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


class InstanceTracker:
    _instances: ClassVar[Runtime[WeakValueDictionary]] = WeakValueDictionary()

    def __post_init__(self) -> None:
        self._instances[uuid4()] = self


@dataclass
class RichFix:
    """Fix rendering for fields of non-dict Mapping type for rich.print"""

    rich_fix: ClassVar[Runtime[bool]] = True

    def __rich__(self):  # pragma: no cover
        if not self.rich_fix:
            return self

        return replace(self, **{
            f.name: dict(getattr(self, f.name)) for f in get_fields(self)
            if isinstance(getattr(self, f.name), Mapping) and f.init
        })


@dataclass
class Map(Mapping[KT, VT], RichFix):
    # _data field must be defined by subclasses
    def __getitem__(self, key: KT) -> VT:
        return self._data[key]  # type: ignore

    def __iter__(self) -> Iterator[KT]:
        return iter(self._data)  # type: ignore

    def __len__(self) -> int:
        return len(self._data)  # type: ignore


@dataclass
class IndexableMap(Map[KT, VT]):
    def __getitem__(self, key: Union[int, KT]) -> VT:
        if isinstance(key, int):
            return list(self._data.values())[key]  # type: ignore

        return self._data[key]  # type: ignore


class JSONLoadError(MioError):
    pass


@dataclass
class JSON(RichFix):
    aliases: ClassVar[Runtime[Dict[str, Union[str, Sequence[str]]]]] = {}

    # Matrix API doesn't like getting floats for time-related stuff
    dumpers: ClassVar[Runtime[Dumpers]] = {
        UUID: lambda self, v: str(v),
        URL: lambda self, v: str(v),
        Path: lambda self, v: str(v),
        Enum: lambda self, v: v.value,
        bytes: lambda self, v: v.decode(),
        datetime: lambda self, v: int(v.timestamp() * 1000),
        timedelta: lambda self, v: int(v.total_seconds() * 1000),
    }

    loaders: ClassVar[Runtime[Loaders]] = {
        bytes: lambda v, p: v.encode(),
        datetime: lambda v, p: datetime.fromtimestamp(v / 1000),
        timedelta: lambda v, p: timedelta(seconds=v / 1000),
    }


    @property
    def parent(self) -> Optional["JSON"]:
        for f in fields_and_classvars(self):
            if annotation_is_parent(f.type):
                return getattr(self, f.name)

        return None


    @property
    def dict(self) -> DictS:
        data: DictS = {}

        for f in fields_and_classvars(self):
            value          = getattr(self, f.name)
            unset_optional = f.default is None and value is None

            if annotation_is_runtime(f.type) or unset_optional:
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
    def from_dict(cls: Type[JSONT], data: DictS, parent) -> JSONT:
        fields = cls._fields_from_dict(data, parent)

        try:
            return cls(**fields)  # type: ignore
        except TypeError as e:
            raise JSONLoadError(cls, fields, next(iter(e.args), ""))


    @classmethod
    def from_json(cls: Type[JSONT], data: str, parent) -> JSONT:
        return cls.from_dict(json.loads(data), parent)


    def but(self, **fields) -> JSONT:
        return replace(self, **fields)  # type: ignore


    def _dump(self, value: Any, name: Optional[str] = None) -> Any:
        # Use any dumper we that suits this value to convert it first

        if name and name in self.dumpers:
            value = self.dumpers[name](self, value)

        if type(value) in self.dumpers:
            value = self.dumpers[type(value)](self, value)

        for parent in deep_find_parent_classes(type(value)):
            if parent in self.dumpers:
                return self.dumpers[parent](self, value)

        # Process nested structures

        if is_dataclass(value) and is_subclass(type(value), JSON):
            return value.dict

        if is_dataclass(value):
            return {
                f.name: self._dump(getattr(value, f.name), f.name)
                for f in fields_and_classvars(value)
                if not annotation_is_runtime(f.type) and
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
    def _fields_from_dict(cls: Type[JSONT], data: DictS, parent) -> DictS:

        if not isinstance(data, dict):
            raise JSONLoadError(data, dict, "Expected dict")

        fields = {}

        for f in get_fields(cls):
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
                fields[f.name] = cls._load(f.type, value, parent, f.name)

        return fields


    @classmethod
    def _load(
        cls,
        annotation: Any,
        value:      Any,
        parent:     Optional["JSON"] = None,
        field_name: Optional[str]    = None,
    ) -> Any:

        typ     = unwrap_annotated(annotation)
        typo    = getattr(typ, "__bound__", typ)
        typo    = getattr(typo, "__origin__", typo)
        value   = cls._apply_loader(typ, value, parent, field_name)

        if typo is Union:
            loadable = cls._get_loadable_type(annotation, value)
            if loadable:
                typ  = unwrap_annotated(loadable)
                typo = getattr(typ, "__bound__", typ)
                typo = getattr(typo, "__origin__", typo)

        datacls = is_dataclass(typ)

        if datacls and is_subclass(typ, JSON) and isinstance(value, Mapping):
            return typ.from_dict(value, parent)

        if datacls and isinstance(value, Mapping):
            return typ(**{
                f.name:
                    parent if parent and annotation_is_parent(f.type) else
                    cls._load(f.type, value[f.name], field_name=f.name)

                for f in get_fields(typ) if f.name in value
            })

        value = cls._auto_cast(typ, value)

        if typo in (Union, Literal) or isinstance(typo, (str, ForwardRef)):
            return value

        if is_subclass(typo, Mapping) and isinstance(value, Mapping):
            if is_subclass(typo, Counter):
                key_type   = getattr(typ, "__args__", (Any,))[0]
                value_type = int
            else:
                key_type, value_type = getattr(typ, "__args__", (Any, Any))

            key_type_origin = getattr(key_type, "__origin__", key_type)

            dct = {
                cls._load(
                    key_type,
                    k if is_subclass(key_type_origin, str) else json.loads(k),
                    parent,
                ): cls._load(value_type, v, parent) for k, v in value.items()
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
                    cls._load(
                        item_types[0 if ... in item_types else i], v, parent,
                    )
                    for i, v in enumerate(value)
                )
            else:
                item_type = getattr(typ, "__args__", (Any,))[0]
                items     = [cls._load(item_type, v, parent) for v in value]

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
        cls,
        annotation: Any,
        value:      Any,
        parent:     Optional["JSON"] = None,
        field_name: Optional[str]    = None,
    ) -> Any:

        if field_name and field_name in cls.loaders:
            try:
                return cls.loaders[field_name](value, parent)
            except Exception as e:
                raise JSONLoadError(cls, field_name, annotation, value, e)

        typ = cls._get_loadable_type(annotation, value)
        if not typ:
            return value

        if typ in cls.loaders:
            try:
                return cls.loaders[typ](value, parent)
            except Exception as e:
                raise JSONLoadError(cls, typ, value, e)

        # This won't work for types like List, Dict, etc
        for parent_cls in deep_find_parent_classes(typ):
            if parent_cls in cls.loaders:
                try:
                    return cls.loaders[parent_cls](value, parent)
                except Exception as e:
                    raise JSONLoadError(cls, parent, value, e)

        return value


    @classmethod
    def _auto_cast(cls, annotation: Any, value: Any) -> Any:
        typ = cls._get_loadable_type(annotation, value)

        # If it's a Literal but incorrect value, typingplus.cast will raise
        if typ is Literal and value == annotation.__args__[0]:
            return value

        if typ:
            try:
                return typingplus.cast(typ, value)
            except Exception as e:
                raise JSONLoadError(cls, annotation, value, e)

        return value


@dataclass
class JSONFile(JSON):
    def __post_init__(self) -> None:
        if not Path(self.path).exists():
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            data = self.json

            if data != "{}":
                with sync_atomic_write(self.path) as out:
                    out.write(data)

    @property
    def path(self) -> AsyncPath:
        raise NotImplementedError()


    async def save(self) -> None:
        await self.path.parent.mkdir(parents=True, exist_ok=True)
        data = self.json

        if data != "{}":
            async with atomic_write(self.path) as out:
                await out.write(data)  # type: ignore


    async def load(self) -> "JSONFile":
        data = await self._read_file()

        for name, value in self._fields_from_dict(data, self.parent).items():
            setattr(self, name, value)

        return self


    async def _read_file(self) -> DictS:
        if await self.path.exists():
            return json.loads(await self.path.read_text())

        return {}


def annotation_is_runtime(ann: Any) -> bool:
    if get_origin(ann) is ClassVar and ann.__args__:
        ann = ann.__args__[0]
    return get_origin(ann) is Annotated and _Runtime in ann.__metadata__


def annotation_is_parent(ann: Any) -> bool:
    return get_origin(ann) is Annotated and _Parent in ann.__metadata__


def unwrap_annotated(ann: Any) -> Any:
    return ann.__origin__ if get_origin(ann) is Annotated else ann


def fields_and_classvars(datacls) -> Tuple[Field, ...]:
    return tuple(datacls.__dataclass_fields__.values())


def is_subclass(value: Any, typ: Any) -> bool:
    if value is Any or typ is Any:
        return typ is value
    return issubclass(value, typ)
