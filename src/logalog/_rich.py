"""Render records and Rich objects for the Rich stderr mode.

Only the Rich stderr mode and Rich message objects import this module.
"""

from __future__ import annotations

from logging import LogRecord
from types import TracebackType
from typing import TYPE_CHECKING, cast

from rich.console import Console, ConsoleRenderable, Group, RenderableType
from rich.logging import RichHandler
from rich.text import Text
from rich.traceback import Traceback

from ._logger import _CONSOLE_TRACEBACK, _RICH_SNAPSHOT

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


class _ConsoleSink:
    """Present a destination-local copy of each event through the Rich handler."""

    def __init__(self, handler: _SnapshotHandler, enqueue: bool) -> None:
        self._handler = handler
        self._enqueue = enqueue

    def write(self, message: Message) -> None:
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


def create_console_sink(enqueue: bool) -> _ConsoleSink:
    """Create the Rich stderr sink with one reusable console.

    Parameters
    ----------
    enqueue : bool
        Records arrive through the queue with plain traceback text.

    Returns
    -------
    _ConsoleSink
        Sink that follows the current ``sys.stderr``.
    """
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
    return _ConsoleSink(handler, enqueue)
