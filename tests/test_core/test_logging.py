# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

import asyncio
import re
import sys
from pathlib import Path
from typing import Optional

from mio.client import Client
from mio.core.logging import unexpected_errors_logger
from pytest import mark

pytestmark = mark.asyncio


async def test_terminal_logging(tmp_path: Path, capsys):
    def line_match(
        level: str, text: str = "test", matches: Optional[str] = None,
    ) -> None:

        if matches is None:
            matches = capsys.readouterr().err

        assert re.match(
            rf"^\d\d:\d\d:\d\d {re.escape(level)} {re.escape(text)}"
            rf" +[a-zA-Z\d_.]+:\d+\n$",
            matches,
        )

    async with Client(tmp_path) as client:
        client.debug("test")
        assert not capsys.readouterr().err

        client.info("test")
        line_match("i")

        client.warn("test")
        line_match("!")

        client.err("test")
        line_match("X")

        client.crit("test")
        line_match("F")

        err = RuntimeError("test")

        def check_trace_err(line_re_txt: str = "test"):
            text = capsys.readouterr().err
            line_match("X", line_re_txt, text.splitlines()[0] + "\n")
            assert len(text.splitlines()) > 3
            assert type(err).__name__ in text

        try:
            raise err
        except type(err):
            client.exception("test")
            check_trace_err()

        with client.report(type(err), level="ERROR", trace=True):
            raise err

        check_trace_err(repr(err))  # type: ignore

        with client.report(type(err), trace=False):
            raise err

        line_match("!", repr(err))


async def test_remove_terminal_logging(tmp_path: Path, capsys):
    async with Client(tmp_path) as client:
        client.remove_terminal_logging()
        client.crit("test")
        assert not capsys.readouterr().err
        assert await client.current_log_file.read_text()


async def test_file_logging(tmp_path: Path):
    async def entry_match(
        level: str, text: str = "test", matches: Optional[str] = None,
    ) -> None:

        if matches is None:
            matches = await client.current_log_file.read_text()

        assert re.match(
            rf"^{re.escape(level)} \d{{4}}-\d\d-\d\d \d\d:\d\d:\d\d\.\d\d\d "
            rf"[a-zA-Z\d_.]+:\d+\n{re.escape(text)}\n\n$",
            matches,
        )

        await client.current_log_file.write_text("")

    async with Client(tmp_path) as client:
        client.debug("test")
        await entry_match("DEBUG")

        client.info("test")
        await entry_match("INFO")

        client.warn("test")
        await entry_match("WARNING")

        client.err("test")
        await entry_match("ERROR")

        client.crit("test")
        await entry_match("CRITICAL")

        err = RuntimeError("test")

        async def check_trace_err(entry_txt: str = "test"):
            text = await client.current_log_file.read_text()
            await client.current_log_file.write_text("")

            msg = "\n".join(text.splitlines()[:2]) + "\n\n"
            await entry_match("ERROR", entry_txt, msg)
            assert len(text.splitlines()) > 3
            assert type(err).__name__ in text
            assert "Version with locals:" in text

        try:
            raise err
        except type(err):
            client.exception("test")
            await check_trace_err()

        with client.report(type(err), level="ERROR", trace=True):
            raise err

        await check_trace_err(repr(err))  # type: ignore

        with client.report(type(err), trace=False):
            raise err

        await entry_match("WARNING", repr(err))


async def test_file_retention(tmp_path: Path):
    for i in range(1, 11):
        async with Client(tmp_path) as client:
            client.info("test {}", i)

    log_dir = tmp_path / "logs"
    assert len(list(log_dir.iterdir())) == 10
    assert len(list(log_dir.glob("????????-??????.??????.log"))) == 10

    async with Client(tmp_path) as client:
        client.info("test 11")

    files = sorted(log_dir.iterdir(), key=lambda f: f.name)
    assert len(files) == 10
    await asyncio.sleep(1)
    assert "test 2" in files[0].read_text()
    assert "test 11" in files[-1].read_text()


async def test_report_caught(tmp_path: Path):
    async with Client(tmp_path) as client:
        with client.report(ValueError, TypeError) as caught:
            pass

        assert caught == []

        with client.report(ValueError, TypeError) as caught:
            raise TypeError

        assert len(caught) == 1  # type: ignore
        assert isinstance(caught[0], TypeError)


async def test_except_hook(tmp_path: Path, capsys):
    assert sys.excepthook is unexpected_errors_logger

    async with Client(tmp_path / "1") as c1, Client(tmp_path / "2") as c2:
        def get_keyboard_interrupt() -> KeyboardInterrupt:
            try:
                raise KeyboardInterrupt
            except KeyboardInterrupt as e:
                return e

        ignored = get_keyboard_interrupt()
        assert ignored.__traceback__
        sys.excepthook(type(ignored), ignored, ignored.__traceback__)

        assert "Unexpected general error" not in capsys.readouterr().err
        assert not await c1.current_log_file.read_text()
        assert not await c2.current_log_file.read_text()

        def get_runtime_error() -> RuntimeError:
            try:
                raise RuntimeError
            except RuntimeError as e:
                return e

        caught = get_runtime_error()
        assert caught.__traceback__
        sys.excepthook(type(caught), caught, caught.__traceback__)

        assert "Unexpected general error" in capsys.readouterr().err
        assert await c1.current_log_file.read_text()
        assert await c2.current_log_file.read_text()
