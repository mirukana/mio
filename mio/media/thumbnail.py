from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING, Optional

from aiopath import AsyncPath

from ..core.data import AutoStrEnum, Parent
from ..core.files import remove_write_permissions
from ..core.ids import MXC

if TYPE_CHECKING:
    from .store import MediaStore


class ThumbnailMode(AutoStrEnum):
    crop  = auto()
    scale = auto()


class ThumbnailForm(Enum):
    tiny   = (32, 32, ThumbnailMode.crop)
    small  = (96, 96, ThumbnailMode.crop)
    medium = (320, 240, ThumbnailMode.scale)
    large  = (640, 480, ThumbnailMode.scale)
    huge   = (800, 600, ThumbnailMode.scale)


    def __init__(self, width: int, height: int, mode: ThumbnailMode) -> None:
        # These will be available on the members, e.g. ThumbnailMode.tiny.width
        self.width  = width
        self.height = height
        self.mode   = mode


    @classmethod
    def best_match(
        cls, width: int, height: int, mode: Optional[ThumbnailMode] = None,
    ) -> "ThumbnailForm":

        for form in reversed(cls):  # type: ignore
            if mode and form.mode != mode:
                continue

            if width >= form.width or height >= form.height:
                return form

        return cls.medium if mode is ThumbnailMode.scale else cls.tiny


@dataclass
class Thumbnail:
    store:   Parent["MediaStore"]
    for_mxc: MXC
    form:    ThumbnailForm


    @property
    def file(self) -> AsyncPath:
        name = f"{self.form.width}x{self.form.height}-{self.form.mode.value}"
        return self.store._mxc_path(self.for_mxc).with_name(name)


    async def remove(self) -> None:
        await self.file.unlink()


    def _partial_file(self) -> AsyncPath:
        return self.store._partial_path(self.for_mxc).with_name(self.file.name)


    async def _adopt_file(self, path: AsyncPath) -> None:
        await self.file.parent.mkdir(parents=True, exist_ok=True)
        await path.replace(self.file)
        await remove_write_permissions(self.file)
