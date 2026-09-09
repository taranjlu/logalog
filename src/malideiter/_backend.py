"""Isolate the Loguru compatibility boundary and Rich output."""

from collections.abc import Mapping

from beartype import beartype
from loguru._logger import Core, Logger
from rich.console import Console
from rich.logging import RichHandler


@beartype
def _message_format(record: Mapping[str, object]) -> str:
    """Let Rich format exceptions instead of appending a second traceback."""
    return "{message}"


@beartype
def create_backend() -> Logger:
    """Create a private synchronous logger with one reusable stderr console.

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
        enqueue=False,
        backtrace=False,
        diagnose=False,
        catch=False,
    )
    return backend
