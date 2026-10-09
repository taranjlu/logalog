"""Isolate the Loguru compatibility boundary and the stderr output modes."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from contextlib import suppress
from functools import partial
from traceback import TracebackException
from typing import TYPE_CHECKING, cast

from loguru._logger import Core, Logger
from loguru._recattrs import RecordException

from ._configuration import FileDestination, Stderr
from ._logger import _CONSOLE_TRACEBACK, _RICH_SNAPSHOT

if TYPE_CHECKING:
    from loguru import Message, Record


def _message_format(record: Mapping[str, object]) -> str:
    """Let each stderr sink format exceptions instead of appending a second traceback."""
    return "{message}"


def _prepare_console(record: dict[str, object], *, traceback_text: bool) -> None:
    """Keep presentation data outside native JSON fields without mutating the event."""
    extra = cast(dict[str, object], record["extra"])
    record[_RICH_SNAPSHOT] = extra.pop(_RICH_SNAPSHOT, None)
    exception = cast(RecordException | None, record["exception"])
    if traceback_text and exception is not None and exception.type is not None:
        record[_CONSOLE_TRACEBACK] = "".join(
            TracebackException(exception.type, exception.value, exception.traceback).format()
        ).rstrip()


def _field(value: object) -> str:
    """Show one field value without spaces or quotes that would break the line."""
    if isinstance(value, str) and value and not any(c.isspace() or c in '="' for c in value):
        return value
    return json.dumps(value, default=str, ensure_ascii=False)


def _plain_line(record: Record) -> str:
    """Format one readable line with the attached fields."""
    time = record["time"]
    line = (
        f"{time:%Y-%m-%d %H:%M:%S}.{time.microsecond // 1000:03d} | "
        f"{record['level'].name:<8} | "
        f"{record['name']}:{record['function']}:{record['line']} - {record['message']}"
    )
    if record["extra"]:
        line += " | " + " ".join(f"{key}={_field(value)}" for key, value in record["extra"].items())
    if traceback := cast(dict[str, object], record).get(_CONSOLE_TRACEBACK):
        line += f"\n{traceback}"
    return line


def _json_line(record: Record) -> str:
    """Format one JSON Lines record with the attached fields."""
    exception = record["exception"]
    return json.dumps(
        {
            "time": record["time"].isoformat(),
            "level": record["level"].name,
            "name": record["name"],
            "function": record["function"],
            "line": record["line"],
            "process": record["process"].id,
            "thread": record["thread"].name,
            "message": record["message"],
            "extra": record["extra"],
            "exception": None
            if exception is None or exception.type is None
            else {
                "type": exception.type.__name__,
                "value": str(exception.value),
                "traceback": cast(dict[str, object], record).get(_CONSOLE_TRACEBACK),
            },
        },
        default=str,
        ensure_ascii=False,
    )


class _StreamSink:
    """Write plain or JSON lines to the current ``sys.stderr``."""

    def __init__(self, stderr: Stderr) -> None:
        self._format = _json_line if stderr == "json" else _plain_line

    def write(self, message: Message) -> None:
        """Write one record and flush the stream."""
        stream = sys.stderr
        stream.write(self._format(message.record) + "\n")
        stream.flush()


def close_backend(backend: Logger) -> None:
    """Remove every handler, then raise the first close failure.

    Parameters
    ----------
    backend : Logger
        Private Loguru logger to close.

    Raises
    ------
    Exception
        The first failure that a handler raised while it closed.
    """
    failure: Exception | None = None
    for handler_id in list(backend._core.handlers):
        try:
            backend.remove(handler_id)
        except Exception as error:
            # Close later handlers before the first failure propagates.
            failure = failure or error
    if failure is not None:
        raise failure


def create_backend(
    *, enqueue: bool = True, files: Sequence[FileDestination] = (), stderr: Stderr = "rich"
) -> Logger:
    """Create a private logger with one stderr sink.

    Parameters
    ----------
    enqueue : bool, default=True
        Send records through Loguru's multiprocessing queue.
    files : Sequence[FileDestination], default=()
        Native file destinations owned by this backend.
    stderr : Stderr, default="rich"
        Stderr output mode.

    Returns
    -------
    Logger
        Private Loguru logger with its sinks.

    Notes
    -----
    Loguru has no public factory for an empty, independent logger. Copying its
    shared logger fails with existing file sinks. Keep this private constructor
    boundary tested against the supported Loguru version range.
    """
    backend = Logger(
        core=Core(),
        exception=None,
        depth=0,
        record=False,
        lazy=False,
        colors=False,
        raw=False,
        capture=True,
        patchers=[],
        extra={},
    )
    backend.level("VERBOSE", no=15, color="<blue>", icon="")
    # Rich renders live tracebacks itself. Other modes and the queue need plain text.
    backend = backend.patch(partial(_prepare_console, traceback_text=enqueue or stderr != "rich"))
    try:
        if stderr == "rich":
            from ._rich import create_console_sink

            sink: object = create_console_sink(enqueue)
        else:
            sink = _StreamSink(stderr)
        backend.add(
            sink,
            level=0,
            format=_message_format,
            colorize=False,
            enqueue=enqueue,
            backtrace=False,
            diagnose=False,
            catch=False,
        )
        for destination in files:
            backend.add(
                destination.path,
                level=0,
                format=(
                    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | "
                    "{name}:{function}:{line} - {message}"
                ),
                serialize=destination.kind == "json",
                colorize=False,
                enqueue=enqueue,
                backtrace=False,
                diagnose=False,
                catch=False,
                rotation=destination.rotation,
                retention=destination.retention,
                compression=destination.compression,
                delay=destination.delay,
                watch=destination.watch,
                mode=destination.mode,
                encoding=destination.encoding,
                buffering=destination.buffering,
            )
    except BaseException:
        with suppress(Exception):
            close_backend(backend)
        raise
    return backend
