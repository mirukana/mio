# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from dataclasses import dataclass
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from typing import (
    TYPE_CHECKING, Any, ClassVar, Dict, Optional, Set, Type, TypeVar, Union,
)

import aiofiles
from bs4 import BeautifulSoup
from PIL import Image as PILImage

from ...core.contents import EventContent
from ...core.files import (
    SeekableIO, guess_mime, has_transparency, measure, media_info,
    read_whole_binary, save_jpg, save_png,
)
from ...core.html import html2markdown, plain2html
from ...core.ids import MXC, EventId
from ...core.transfer import TransferUpdateCallback
from ...e2e.contents import EncryptedMediaInfo
from ..events import TimelineEvent

if TYPE_CHECKING:
    from ...client import Client

TexT     = TypeVar("TexT", bound="Textual")
ContentT = TypeVar("ContentT", bound="EventContent")

THUMBNAIL_POSSIBLE_PIL_FORMATS: Set[str] = {"PNG", "JPEG"}
THUMBNAIL_SIZE_MAX_OF_ORIGINAL: float    = 0.9  # must be <90% of orig size

HTML_FORMAT         = "org.matrix.custom.html"
MATRIX_TO           = "https://matrix.to/#"
HTML_REPLY_FALLBACK = (
    "<mx-reply>"
        "<blockquote>"
            '<a href="{matrix_to}/{room_id}/{event_id}">In reply to</a> '
            '<a href="{matrix_to}/{user_id}">{user_id}</a>'
            "<br>"
            "{content}"
        "</blockquote>"
    "</mx-reply>"
)


# Base classes

@dataclass
class Message(EventContent):
    type = "m.room.message"

    msgtype: ClassVar[Optional[str]] = None

    body: str


    @classmethod
    def matches(cls, event: Dict[str, Any]) -> bool:
        if not cls.msgtype:
            return False

        msgtype = event.get("content", {}).get("msgtype")
        return super().matches(event) and cls.msgtype == msgtype


@dataclass
class Textual(Message):
    aliases = {"in_reply_to": ["m.relates_to", "m.in_reply_to", "event_id"]}

    format:         Optional[str]     = None
    formatted_body: Optional[str]     = None
    replies_to:     Optional[EventId] = None


    @classmethod
    def from_html(cls: Type[TexT], html: str, plaintext: str = None) -> TexT:
        if plaintext is None:
            soup           = BeautifulSoup(html, "html.parser")
            reply_fallback = soup.find("mx-reply")

            if reply_fallback:
                reply_fallback.extract()
                html = str(soup)

            plaintext = html2markdown(html)

        if plaintext == html:
            return cls(plaintext)

        return cls(plaintext, HTML_FORMAT, html)


    @property
    def html_no_reply_fallback(self) -> Optional[str]:
        if self.format != HTML_FORMAT:
            return None

        soup     = BeautifulSoup(self.formatted_body or "", "html.parser")
        fallback = soup.find("mx-reply")

        if fallback:
            fallback.extract()
            return str(soup)

        return self.formatted_body


    def replying_to(self: TexT, event: TimelineEvent) -> TexT:
        content = event.content
        body = content.body if isinstance(content, Message) else content.type

        new_plaintext = "\n".join(
            f"> <{event.sender}> {line}" if i == 0 else f"> {line}"
            for i, line in enumerate(body.splitlines())
        ) + "\n\n" + self.body

        new_html = HTML_REPLY_FALLBACK.format(
            matrix_to = MATRIX_TO,
            room_id   = event.room.id,
            event_id  = event.id,
            user_id   = event.sender,
            content   =
                getattr(content, "formatted_body", "") or plain2html(body),
        ) + (self.formatted_body or plain2html(self.body))

        return self.but(
            body           = new_plaintext,
            format         = HTML_FORMAT,
            formatted_body = new_html,
            replies_to     = event.id,
        )


@dataclass
class Media(Message):
    aliases = {
        "mxc": ["url"], "encrypted": ["file"], "mime": ["info", "mimetype"],
    }

    mxc:       Optional[MXC]                = None
    encrypted: Optional[EncryptedMediaInfo] = None
    mime:      Optional[str]                = None
    size:      Optional[int]                = None


    def __post_init__(self) -> None:
        if not self.mxc and not self.encrypted:
            raise TypeError(f"{self} missing both mxc and encrypted fields")


    @classmethod
    async def from_data(
        cls,
        client:                 "Client",
        data:                   SeekableIO,
        encrypt:                bool                   = False,
        filename:               Optional[str]          = None,
        body:                   Optional[str]          = None,
        on_upload_update:       TransferUpdateCallback = None,
        on_thumb_upload_update: TransferUpdateCallback = None,
    ) -> "Media":

        body  = body or filename or ""
        mime  = await guess_mime(data)
        size  = await measure(data)
        media = await client.media.upload(
            data, filename, on_upload_update, encrypt,
        )

        base = mime.split("/")[0]
        cls  = {"image": Image, "video": Video, "audio": Audio}.get(base, File)

        if encrypt:
            ref      = await media.last_reference(encrypted=True)
            injson   = await ref.decrypt_file.read_text()
            info     = EncryptedMediaInfo.from_json(injson, parent=None)
            info.mxc = ref.mxc
            obj      = cls(body, encrypted=info, mime=mime, size=size)
        else:
            mxc = await media.last_mxc(encrypted=False)
            obj = cls(body, mxc, mime=mime, size=size)

        if isinstance(obj, Visual):
            await Visual._set_dimensions(obj, data)

        if isinstance(obj, Playable):
            await Playable._set_duration(obj, data)

        if isinstance(obj, Thumbnailable):
            args = (obj, client, data, mime, encrypt, on_thumb_upload_update)
            await Thumbnailable._set_thumbnail(*args)

        if isinstance(obj, File):
            obj.filename = filename

        return obj


    @classmethod
    async def from_path(
        cls,
        client:                 "Client",
        path:                   Union[Path, str],
        encrypt:                bool                   = False,
        body:                   Optional[str]          = None,
        on_upload_update:       TransferUpdateCallback = None,
        on_thumb_upload_update: TransferUpdateCallback = None,
    ) -> "Media":

        async with aiofiles.open(path, "rb") as file:
            name = Path(path).name
            cbs  = (on_upload_update, on_thumb_upload_update)
            return await cls.from_data(client, file, encrypt, name, body, *cbs)


@dataclass
class Visual(Media):
    aliases = {
        **Media.aliases, "width": ["info", "w"], "height": ["info", "h"],
    }

    width:  Optional[int] = None
    height: Optional[int] = None


    async def _set_dimensions(self, data: SeekableIO) -> bool:
        tracks      = (await media_info(data)).tracks
        widths      = (int(getattr(t, "width", 0) or 0) for t in tracks)
        heights     = (int(getattr(t, "height", 0) or 0) for t in tracks)
        self.width  = max((w for w in widths if w), default=None)
        self.height = max((h for h in heights if h), default=None)
        return bool(self.width or self.height)


@dataclass
class Playable(Media):
    aliases = {**Media.aliases, "duration":  ["info", "duration"]}

    duration: Optional[timedelta] = None


    async def _set_duration(self, data: SeekableIO) -> bool:
        tracks        = (await media_info(data)).tracks
        durations     = (float(getattr(t, "duration", 0) or 0) for t in tracks)
        long          = max((d for d in durations if d), default=None)
        self.duration = timedelta(seconds=long / 1000 / 60) if long else None
        return bool(self.duration)


@dataclass
class Thumbnailable(Media):
    aliases = {
        **Media.aliases,
        "thumbnail_mxc":       ["info", "thumbnail_url"],
        "thumbnail_encrypted": ["info", "thumbnail_file"],
        "thumbnail_width":     ["info", "thumbnail_info", "w"],
        "thumbnail_height":    ["info", "thumbnail_info", "h"],
        "thumbnail_mime":      ["info", "thumbnail_info", "mimetype"],
        "thumbnail_size":      ["info", "thumbnail_info", "size"],
    }

    thumbnail_mxc:       Optional[MXC]                = None
    thumbnail_encrypted: Optional[EncryptedMediaInfo] = None
    thumbnail_width:     Optional[int]                = None
    thumbnail_height:    Optional[int]                = None
    thumbnail_mime:      Optional[str]                = None
    thumbnail_size:      Optional[int]                = None


    async def _set_thumbnail(
        self,
        client:           "Client",
        data:             SeekableIO,
        mime:             str,
        encrypt:          bool                   = False,
        on_upload_update: TransferUpdateCallback = None,
    ) -> Optional[bytes]:

        if mime.split("/")[0] != "image" or mime == "image/svg+xml":  # TODO
            return None

        full_bytes     = await read_whole_binary(data)
        image          = PILImage.open(BytesIO(full_bytes))  # XXX may raise
        full_format_ok = image.format in THUMBNAIL_POSSIBLE_PIL_FORMATS

        if image.width > 800 or image.height > 600:
            image.thumbnail((800, 600), resample=PILImage.LANCZOS)

        thumb_bytes = await save_png(image)
        jpg_bytes   = b""
        mime        = "image/png"
        ratio       = THUMBNAIL_SIZE_MAX_OF_ORIGINAL

        if not has_transparency(image):
            jpg_bytes = await save_jpg(image)

        if jpg_bytes and len(jpg_bytes) < len(thumb_bytes):
            thumb_bytes = jpg_bytes
            mime        = "image/jpeg"

        if full_format_ok and len(thumb_bytes) > len(full_bytes) * ratio:
            return None

        media = await client.media.upload(
            BytesIO(thumb_bytes), on_update=on_upload_update, encrypt=encrypt,
        )

        if encrypt:
            ref    = await media.last_reference(encrypted=True)
            injson = await ref.decrypt_file.read_text()
            info   = EncryptedMediaInfo.from_json(injson, parent=None)

            self.thumbnail_encrypted = info.but(mxc=ref.mxc)
        else:
            self.thumbnail_mxc = await media.last_mxc(encrypted=False)

        self.thumbnail_width  = image.width
        self.thumbnail_height = image.height
        self.thumbnail_mime   = mime
        self.thumbnail_size   = len(thumb_bytes)
        return thumb_bytes


# Concrete classes

@dataclass
class Text(Textual):
    msgtype = "m.text"


@dataclass
class Emote(Textual):
    msgtype = "m.emote"


@dataclass
class Notice(Textual):
    msgtype = "m.notice"


@dataclass
class File(Thumbnailable):
    msgtype = "m.file"

    filename: Optional[str] = None


@dataclass
class Image(Visual, Thumbnailable):
    aliases = {**Visual.aliases, **Thumbnailable.aliases}
    msgtype = "m.image"


@dataclass
class Audio(Playable):
    msgtype = "m.audio"


@dataclass
class Video(Visual, Playable, Thumbnailable):
    aliases = {**Visual.aliases, **Playable.aliases, **Thumbnailable.aliases}
    msgtype = "m.video"


@dataclass
class Redaction(EventContent):
    type = "m.room.redaction"

    reason: Optional[str] = None
