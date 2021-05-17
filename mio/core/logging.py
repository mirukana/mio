# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

import logging
import sys
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from io import StringIO
from pathlib import Path
from types import TracebackType
from typing import Any, ClassVar, Dict, Iterator, List, Optional, Type, Union
from uuid import uuid4
from weakref import WeakValueDictionary

import loguru
from aiopath import AsyncPath
from loguru._logger import Logger
from rich.console import Console
from rich.logging import RichHandler
from rich.text import Text as RichText
from rich.traceback import Traceback as RichTraceback

from .data import Runtime


@dataclass
class MioLogger:
    _instances: ClassVar[Runtime[WeakValueDictionary]] = WeakValueDictionary()

    logger:        Runtime[Logger]   = field(init=False, repr=False)
    creation:      Runtime[datetime] = field(init=False, repr=False)
    _term_sink_id: Runtime[int]      = field(init=False, repr=False)


    def __post_init__(self) -> None:
        self.creation            = datetime.now()
        self._instances[uuid4()] = self
        self._reconfigure_logging()


    @property
    def path(self) -> AsyncPath:
        raise NotImplementedError


    @property
    def current_log_file(self) -> AsyncPath:
        filename = self.creation.strftime("%Y%m%d-%H%M%S.%f.log")
        return self.path.parent / "logs" / filename


    def remove_terminal_logging(self) -> None:
        self.logger.remove(self._term_sink_id)


    def debug(self, msg: str, *args, depth: int = 0, **kwargs) -> None:
        self.logger.opt(depth=2 + depth).debug(msg, *args, **kwargs)


    def info(self, msg: str, *args, depth: int = 0, **kwargs) -> None:
        self.logger.opt(depth=2 + depth).info(msg, *args, **kwargs)


    def warn(self, msg: str, *args, depth: int = 0, **kwargs) -> None:
        self.logger.opt(depth=2 + depth).warning(msg, *args, **kwargs)


    def err(self, msg: str, *args, depth: int = 0, **kwargs) -> None:
        self.logger.opt(depth=2 + depth).error(msg, *args, **kwargs)


    def crit(self, msg: str, *args, depth: int = 0, **kwargs) -> None:
        self.logger.opt(depth=2 + depth).critical(msg, *args, **kwargs)


    def exception(self, msg: str, *args, depth: int = 0, **kwargs) -> None:
        self.logger.opt(depth=2 + depth).exception(msg, *args, **kwargs)


    @contextmanager
    def report(
        self,
        *types: Type[Exception],
        level:  Union[str, int]  = "WARNING",
        trace:  bool = False,
        depth:  int  = 0,
    ) -> Iterator[List[Exception]]:

        caught: List[Exception] = []

        try:
            yield caught
        except types as e:
            caught.append(e)
            logger = self.logger.opt(depth=3 + depth, exception=trace)
            logger.log(level, repr(e))


    def _reconfigure_logging(self) -> None:
        if hasattr(self, "logger"):
            self.logger.remove()

        loguru.logger.remove()
        self.logger = deepcopy(loguru.logger)  # type: ignore

        # File logging configuration

        def file_format(record: Dict[str, Any]) -> str:
            fmt = (
                "{level} {time:YYYY-MM-DD HH:mm:ss.SSS} "
                "{name}.{function}:{line}\n{message}"
            )

            if record["exception"] is not None:
                try:
                    raise record["exception"].value
                except Exception:
                    out = StringIO()

                    Console(file=out, soft_wrap=True).print(RichTraceback(
                        indent_guides=False, show_locals=False,
                    ))

                    out.write("\nVersion with locals:\n")

                    Console(file=out, soft_wrap=True).print(RichTraceback(
                        indent_guides     = False,
                        show_locals       = True,
                        locals_max_length = None,  # type: ignore
                        locals_max_string = None,  # type: ignore
                    ))

                    record["extra"]["stack"] = out.getvalue()
                    return "%s\n{extra[stack]}\n" % fmt

            return "%s\n\n" % fmt

        file = Path(self.current_log_file)
        file.parent.mkdir(parents=True, exist_ok=True)
        previous_logs = sorted(file.parent.glob("*.log"), key=lambda f: f.name)

        for too_old in previous_logs[-10::-1]:  # keep 9 previous log files max
            too_old.unlink()

        self.logger.add(
            open(file, "a"),  # FIXME: loguru has issues with {} in paths
            level     = logging.NOTSET,
            backtrace = False,
            enqueue   = True,
            format    = file_format,
        )

        # Terminal logging configuration

        term_handler = TermLogHandler(
            console             = Console(file=sys.stderr, soft_wrap=True),
            log_time_format     = "%T",
            omit_repeated_times = False,
            rich_tracebacks     = True,
        )

        self._term_sink_id = self.logger.add(
            sink      = term_handler,
            level     = logging.INFO,
            backtrace = False,
            format    = lambda record: "{message}",
        )


class TermLogHandler(RichHandler):
    level_names = {
        "DEBUG":    "*",
        "INFO":     "i",
        "WARNING":  "!",
        "ERROR":    "X",
        "CRITICAL": "F",
    }

    def get_level_text(self, record):
        return RichText.styled(
            self.level_names[record.levelname],
            f"logging.level.{record.levelname.lower()}",
        )


def unexpected_errors_logger(
    type: Type[BaseException], value: BaseException, traceback: TracebackType,
) -> None:

    if not isinstance(value, Exception):  # ignore KeyboardInterrupt
        sys.__excepthook__(type, value, traceback)
        return

    for logger in MioLogger._instances.values():
        try:
            raise value
        except Exception:
            msg = "Unexpected general error, logged to every existing logger:"
            logger.exception(msg, depth=-2)  # FIXME: depth 0 crashes

    sys.__excepthook__(type, value, traceback)


sys.excepthook = unexpected_errors_logger
