"""Isolate the Loguru compatibility boundary and Rich output."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from os import PathLike
from traceback import TracebackException
from typing import Literal, cast

from beartype import beartype
from loguru._logger import Core, Logger
from loguru._recattrs import RecordException
from rich.console import Console
from rich.logging import RichHandler


@beartype
@dataclass(frozen=True, slots=True)
class FileDestination:
    """Configure one native Loguru file sink.

    Parameters
    ----------
    path : str or PathLike[str]
        File path. Loguru time fields are accepted.
    kind : Literal["text", "json"], default="text"
        Select readable text or JSON Lines output.
    rotation : str or int or None, default="10 MB"
        Native Loguru size or time rotation rule. Use ``None`` to disable it.
    retention : str or int or None, default=5
        Native Loguru archive age or count. Use ``None`` to disable it.
    compression : Literal["gz", "bz2", "xz", "lzma", "tar", "tar.gz",
        "tar.bz2", "tar.xz", "zip"] or None, default=None
        Native Loguru archive compression.
    delay : bool, default=False
        Create the file after the first accepted event.
    watch : bool, default=False
        Reopen a file that an external program replaces.
    mode : Literal["a", "w"], default="a"
        Open the active file for append or replacement.
    encoding : str, default="utf8"
        Text encoding.
    buffering : int, default=1
        File buffering policy.
    """

    path: str | PathLike[str]
    kind: Literal["text", "json"] = "text"
    rotation: str | int | None = "10 MB"
    retention: str | int | None = 5
    compression: (
        Literal["gz", "bz2", "xz", "lzma", "tar", "tar.gz", "tar.bz2", "tar.xz", "zip"] | None
    ) = None
    delay: bool = False
    watch: bool = False
    mode: Literal["a", "w"] = "a"
    encoding: str = "utf8"
    buffering: int = 1


@beartype
def _message_format(record: Mapping[str, object]) -> str:
    """Let Rich format exceptions instead of appending a second traceback."""
    return "{message}"


@beartype
def _preserve_queued_traceback(record: dict[str, object]) -> bool:
    """Render a traceback before Loguru removes it during queue pickling."""
    exception = cast(RecordException | None, record["exception"])
    if exception is None or exception.type is None:
        return True
    record["message"] = "{}\n{}".format(
        record["message"],
        "".join(
            TracebackException(exception.type, exception.value, exception.traceback).format()
        ).rstrip(),
    )
    record["exception"] = None
    return True


@beartype
def create_backend(*, enqueue: bool = True, files: Sequence[FileDestination] = ()) -> Logger:
    """Create a private logger with one reusable stderr console.

    Parameters
    ----------
    enqueue : bool, default=True
        Send records through Loguru's multiprocessing queue.
    files : Sequence[FileDestination], default=()
        Native file destinations owned by this backend.

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
    try:
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
            filter=_preserve_queued_traceback if enqueue else None,
        )
    except BaseException:
        backend.remove()
        raise
    return backend
