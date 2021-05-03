# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator, List, Type

from rich.logging import RichHandler
from rich.text import Text as RichText

from .data import Runtime


@dataclass
class MioLogger:
    logger: Runtime[logging.Logger] = field(
        init            = False,
        repr            = False,
        default_factory = lambda: logging.getLogger("mio"),
    )

    def debug(self, msg: str, *args, **kwargs) -> None:
        self.logger.debug(msg, *args, **kwargs)

    def info(self, msg: str, *args, **kwargs) -> None:
        self.logger.info(msg, *args, **kwargs)

    def warn(self, msg: str, *args, **kwargs) -> None:
        self.logger.warning(msg, *args, **kwargs)

    def err(self, msg: str, *args, **kwargs) -> None:
        self.logger.error(msg, *args, **kwargs)

    def crit(self, msg: str, *args, **kwargs) -> None:
        self.logger.critical(msg, *args, **kwargs)

    def exception(self, msg: str, *args, **kwargs) -> None:
        self.logger.exception(msg, *args, **kwargs)

    @contextmanager
    def report(
        self,
        *types: Type[Exception],
        level:  int  = logging.WARNING,
        trace:  bool = False,
    ) -> Iterator[List[Exception]]:

        caught: List[Exception] = []

        try:
            yield caught
        except types as e:
            caught.append(e)

            if trace:
                self.logger.exception("Caught exception", stacklevel=3)
            else:
                self.logger.log(level, repr(e), stacklevel=3)


class StderrLogHandler(RichHandler):
    ljust       = 1
    level_names = {
        "DEBUG":    "*",
        "INFO":     "i",
        "WARNING":  "!",
        "ERROR":    "X",
        "CRITICAL": "F",
    }

    def get_level_text(self, record):
        lj = self.ljust
        return RichText.styled(
            self.level_names.get(record.levelname, record.levelname).ljust(lj),
            f"logging.level.{record.levelname.lower()}",
        )


logging.basicConfig(
    level    = logging.INFO,
    format   = "%(message)s\n",
    datefmt  = "%T",
    handlers = [
        StderrLogHandler(
            rich_tracebacks     = True,
            omit_repeated_times = False,
            log_time_format     = "%F %T",
        ),
    ],
)
