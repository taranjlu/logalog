"""Provide the typed core logging interface."""

from inspect import currentframe
from threading import Lock
from typing import Literal

from beartype import beartype
from loguru._logger import Logger as LoguruLogger

from ._backend import create_backend

Level = Literal["TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"]


@beartype
class Logger:
    """Send typed log calls to an isolated, lazily initialized backend."""

    def __init__(self) -> None:
        """Keep import free of output and worker threads."""
        self._backend: LoguruLogger | None = None
        self._lock = Lock()

    def _get_backend(self) -> LoguruLogger:
        """Initialize the backend once, including during concurrent first use."""
        with self._lock:
            if self._backend is None:
                self._backend = create_backend()
            return self._backend

    def _emit(
        self,
        level: Level,
        message: str,
        args: tuple[object, ...],
        fields: dict[str, object],
        *,
        exception: bool = False,
    ) -> None:
        """Preserve the external caller through library and Beartype wrappers."""
        backend = self._get_backend()
        frame = currentframe()
        depth = 0
        try:
            while frame is not None and (
                frame.f_globals.get("__name__", "").startswith("malideiter.")
                or frame.f_code.co_filename.startswith("<@beartype(malideiter.")
            ):
                depth += 1
                frame = frame.f_back
        finally:
            del frame

        backend.opt(depth=depth, exception=exception).log(level, message, *args, **fields)

    def log(self, level: Level, message: str, *args: object, **fields: object) -> None:
        """Log a message at a supported severity.

        Parameters
        ----------
        level : Level
            Standard Loguru severity name.
        message : str
            Literal text, or a format template when arguments are supplied.
        *args : object
            Positional format arguments.
        **fields : object
            Named format arguments, also retained as Loguru record data.
        """
        self._emit(level, message, args, fields)

    def trace(self, message: str, *args: object, **fields: object) -> None:
        """Log a trace message."""
        self._emit("TRACE", message, args, fields)

    def debug(self, message: str, *args: object, **fields: object) -> None:
        """Log a debug message."""
        self._emit("DEBUG", message, args, fields)

    def info(self, message: str, *args: object, **fields: object) -> None:
        """Log an information message."""
        self._emit("INFO", message, args, fields)

    def success(self, message: str, *args: object, **fields: object) -> None:
        """Log a success message."""
        self._emit("SUCCESS", message, args, fields)

    def warning(self, message: str, *args: object, **fields: object) -> None:
        """Log a warning message."""
        self._emit("WARNING", message, args, fields)

    def error(self, message: str, *args: object, **fields: object) -> None:
        """Log an error message without an automatic traceback."""
        self._emit("ERROR", message, args, fields)

    def critical(self, message: str, *args: object, **fields: object) -> None:
        """Log a critical message."""
        self._emit("CRITICAL", message, args, fields)

    def exception(self, message: str, *args: object, **fields: object) -> None:
        """Log an error with the currently handled exception, without locals."""
        self._emit("ERROR", message, args, fields, exception=True)
