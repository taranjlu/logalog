"""Isolate the Loguru compatibility boundary and Rich output."""

from collections.abc import Mapping
from traceback import TracebackException
from typing import cast

from beartype import beartype
from loguru._logger import Core, Logger
from loguru._recattrs import RecordException
from rich.console import Console
from rich.logging import RichHandler


@beartype
def _message_format(record: Mapping[str, object]) -> str:
    """Let Rich format exceptions instead of appending a second traceback."""
    return "{message}"


@beartype
def _preserve_queued_traceback(record: dict[str, object]) -> None:
    """Render a traceback before Loguru removes it during queue pickling."""
    exception = cast(RecordException | None, record["exception"])
    if exception is None or exception.type is None:
        return
    record["message"] = "{}\n{}".format(
        record["message"],
        "".join(
            TracebackException(exception.type, exception.value, exception.traceback).format()
        ).rstrip(),
    )
    record["exception"] = None


@beartype
def create_backend(*, enqueue: bool = True) -> Logger:
    """Create a private logger with one reusable stderr console.

    Parameters
    ----------
    enqueue : bool, default=True
        Send records through Loguru's multiprocessing queue.

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
    if enqueue:
        backend = backend.patch(_preserve_queued_traceback)
    console = Console(stderr=True, markup=False, highlight=False)
    handler = RichHandler(
        console=console,
        markup=False,
        highlighter=None,
        rich_tracebacks=True,
        tracebacks_show_locals=False,
        tracebacks_extra_lines=0,
        enable_link_path=False,
        keywords=[],
    )
    backend.add(
        handler,
        level=0,
        format=_message_format,
        colorize=False,
        enqueue=enqueue,
        backtrace=False,
        diagnose=False,
        catch=False,
    )
    return backend
