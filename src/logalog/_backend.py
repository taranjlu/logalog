"""Isolate the Loguru compatibility boundary and Rich output."""

from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from functools import partial
from logging import LogRecord
from os import PathLike
from traceback import TracebackException
from types import TracebackType
from typing import TYPE_CHECKING, Literal, cast

from loguru._logger import Core, Logger
from loguru._recattrs import RecordException
from rich.console import Console, ConsoleRenderable, Group
from rich.logging import RichHandler
from rich.text import Text
from rich.traceback import Traceback

_RICH_SNAPSHOT = "__logalog_rich_snapshot__"
_CONSOLE_TRACEBACK = "__logalog_console_traceback__"

if TYPE_CHECKING:
    from loguru import Message


class _SnapshotHandler(RichHandler):
    """Use a producer-rendered Rich snapshot when one is present."""

    def render_message(self, record: LogRecord, message: str) -> ConsoleRenderable:
        """Return the accepted snapshot without parsing message markup."""
        snapshot = cast(dict[str, object], record.__dict__["extra"]).get(_RICH_SNAPSHOT)
        return snapshot if isinstance(snapshot, Text) else super().render_message(record, message)

    def render(
        self,
        *,
        record: LogRecord,
        traceback: Traceback | None,
        message_renderable: ConsoleRenderable,
    ) -> ConsoleRenderable:
        """Keep producer-rendered snapshots outside the narrower metadata columns."""
        if _RICH_SNAPSHOT not in cast(dict[str, object], record.__dict__["extra"]):
            return super().render(
                record=record,
                traceback=traceback,
                message_renderable=message_renderable,
            )
        header = super().render(record=record, traceback=None, message_renderable=Text(""))
        content = [header, message_renderable]
        if traceback is not None:
            content.append(traceback)
        return Group(*content)


_COMPRESSIONS = frozenset({"gz", "bz2", "xz", "lzma", "tar", "tar.gz", "tar.bz2", "tar.xz", "zip"})
_FILE_CHECKS: dict[str, Callable[[object], bool]] = {
    "path": lambda value: isinstance(value, (str, PathLike)),
    "kind": lambda value: value in ("text", "json"),
    "rotation": lambda value: value is None or type(value) in (str, int),
    "retention": lambda value: value is None or type(value) in (str, int),
    "compression": lambda value: (
        value is None or (isinstance(value, str) and value in _COMPRESSIONS)
    ),
    "delay": lambda value: type(value) is bool,
    "watch": lambda value: type(value) is bool,
    "mode": lambda value: value in ("a", "w"),
    "encoding": lambda value: type(value) is str,
    "buffering": lambda value: type(value) is int,
}


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

    def __post_init__(self) -> None:
        """Reject a value that could write records to an unintended file or format.

        Raises
        ------
        ValueError
            If a field has an unsupported type or value.
        """
        for name, valid in _FILE_CHECKS.items():
            if not valid(getattr(self, name)):
                raise ValueError(f"invalid {name}")


def _message_format(record: Mapping[str, object]) -> str:
    """Let Rich format exceptions instead of appending a second traceback."""
    return "{message}"


def _prepare_console(record: dict[str, object], *, enqueue: bool) -> None:
    """Keep presentation data outside native JSON fields without mutating the event."""
    extra = cast(dict[str, object], record["extra"])
    record[_RICH_SNAPSHOT] = extra.pop(_RICH_SNAPSHOT, None)
    exception = cast(RecordException | None, record["exception"])
    if enqueue and exception is not None and exception.type is not None:
        record[_CONSOLE_TRACEBACK] = "".join(
            TracebackException(exception.type, exception.value, exception.traceback).format()
        ).rstrip()


class _ConsoleSink:
    """Present a destination-local copy of each event through the Rich handler."""

    def __init__(self, handler: _SnapshotHandler, enqueue: bool) -> None:
        self._handler = handler
        self._enqueue = enqueue

    def write(self, message: "Message") -> None:
        """Convert one Loguru event to a standard record with its original metadata."""
        source = message.record
        presentation = cast(dict[str, object], source)
        snapshot = presentation.get(_RICH_SNAPSHOT)
        text = source["message"]
        exception = source["exception"]
        if self._enqueue and (traceback := presentation.get(_CONSOLE_TRACEBACK)):
            text = f"{text}\n{traceback}"
            if isinstance(snapshot, Text):
                snapshot = snapshot.copy()
                snapshot.append(f"\n{traceback}")
            exception = None
        extra = dict(source["extra"])
        if isinstance(snapshot, Text):
            extra[_RICH_SNAPSHOT] = snapshot
        record = LogRecord(
            source["name"] or "",
            source["level"].no,
            source["file"].path,
            source["line"],
            text,
            (),
            cast(
                tuple[type[BaseException], BaseException, TracebackType | None] | None,
                (exception.type, exception.value, exception.traceback) if exception else None,
            ),
            source["function"],
        )
        record.extra = extra
        if exception:
            record.exc_text = "\n"
        record.levelname = source["level"].name
        # Show event time and the producer, not delivery time and the writer thread.
        record.created = source["time"].timestamp()
        record.msecs = source["time"].microsecond // 1000
        record.thread = source["thread"].id
        record.threadName = source["thread"].name
        record.process = source["process"].id
        record.processName = source["process"].name
        self._handler.handle(record)

    def stop(self) -> None:
        """Close the Rich handler."""
        self._handler.close()


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
    backend = backend.patch(partial(_prepare_console, enqueue=enqueue))
    try:
        console = Console(stderr=True, markup=False, highlight=False)
        handler = _SnapshotHandler(
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
            _ConsoleSink(handler, enqueue),
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
