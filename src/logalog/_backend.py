"""Isolate the Loguru compatibility boundary and Rich output."""

from collections.abc import Mapping, Sequence
from contextlib import suppress
from functools import partial
from logging import LogRecord
from traceback import TracebackException
from types import TracebackType
from typing import TYPE_CHECKING, cast

from loguru._logger import Core, Logger
from loguru._recattrs import RecordException
from rich.console import Console, ConsoleRenderable, Group, RenderableType
from rich.logging import RichHandler
from rich.text import Text
from rich.traceback import Traceback

from ._configuration import FileDestination
from ._logger import _RICH_SNAPSHOT

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


def create_renderer() -> Console:
    """Create the producer console that renders Rich objects to snapshots.

    Returns
    -------
    Console
        Console that follows the current stderr width and color support.
    """
    return Console(stderr=True, markup=False, highlight=False)


def render_snapshot(console: Console, message: RenderableType, indentation: str | None) -> Text:
    """Render a Rich object to styled text before queue submission.

    Parameters
    ----------
    console : Console
        Producer console from :func:`create_renderer`.
    message : RenderableType
        Rich object to render.
    indentation : str or None
        Section indentation for each line, or ``None`` outside a section.

    Returns
    -------
    Text
        Stable styled snapshot.
    """
    options = console.options
    if indentation is not None:
        options = options.update_width(max(1, options.max_width - len(indentation)))
    snapshot = Text.assemble(
        *(
            (segment.text, segment.style) if segment.style else segment.text
            for segment in console.render(message, options)
        )
    )
    if indentation is None:
        return snapshot
    if snapshot.plain.endswith("\n"):
        snapshot = snapshot[:-1]
    return Text(indentation) + Text(f"\n{indentation}").join(snapshot.split(allow_blank=True))


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
