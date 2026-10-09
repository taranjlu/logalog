"""Route standard logging records through logalog under an explicit ownership policy.

Only ``standard_logging=True`` imports this module.
"""

import logging
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from ._logger import Level, Logger

# Map a standard level number to the highest logalog level at or below it.
_LEVELS: tuple[tuple[int, "Level"], ...] = (
    (50, "CRITICAL"),
    (40, "ERROR"),
    (30, "WARNING"),
    (25, "SUCCESS"),
    (20, "INFO"),
    (15, "VERBOSE"),
    (10, "DEBUG"),
)


class _Handler(logging.Handler):
    """Send standard records to one logalog logger."""

    def __init__(self, logger: "Logger") -> None:
        super().__init__()
        self._logger = logger

    def emit(self, record: logging.LogRecord) -> None:
        """Forward one record with its mapped level and source."""
        level = next((name for number, name in _LEVELS if record.levelno >= number), "TRACE")
        try:
            self._logger._forward(level, record)
        except Exception:
            self.handleError(record)


class Takeover(NamedTuple):
    """Store the root logger state that existed before the takeover."""

    handler: logging.Handler
    handlers: tuple[logging.Handler, ...]
    level: int


def take_over(logger: "Logger", level: int) -> Takeover:
    """Replace the root handlers with one logalog handler.

    Parameters
    ----------
    logger : Logger
        Logger that receives every standard record.
    level : int
        Root level. Lower levels stop in the standard logger at almost no cost.

    Returns
    -------
    Takeover
        Previous root handlers and level for :func:`restore`.
    """
    root = logging.getLogger()
    takeover = Takeover(_Handler(logger), tuple(root.handlers), root.level)
    for handler in takeover.handlers:
        root.removeHandler(handler)
    root.addHandler(takeover.handler)
    root.setLevel(level)
    return takeover


def restore(takeover: Takeover) -> None:
    """Remove the logalog handler and restore the recorded root handlers and level.

    Parameters
    ----------
    takeover : Takeover
        State that :func:`take_over` returned.
    """
    root = logging.getLogger()
    root.removeHandler(takeover.handler)
    for handler in takeover.handlers:
        root.addHandler(handler)
    root.setLevel(takeover.level)
