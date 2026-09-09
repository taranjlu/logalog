"""Provide the typed core logging interface."""

from inspect import currentframe
from os import getpid
from threading import RLock
from typing import Literal, cast

from beartype import beartype
from loguru._logger import Logger as LoguruLogger

from ._backend import create_backend

Level = Literal["TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"]


@beartype
class Logger:
    """Send typed log calls to an isolated, lazily initialized backend."""

    def __init__(self, *, synchronous: bool = False) -> None:
        """Keep import free of output and worker threads."""
        self._backend: LoguruLogger | None = None
        self._lock = RLock()
        self._synchronous = synchronous
        self._owner_pid: int | None = None
        self._closed = False

    def _get_backend(self) -> LoguruLogger:
        """Initialize the backend once, including during concurrent first use."""
        with self._lock:
            if self._closed:
                raise RuntimeError("Logger is shut down")
            if self._backend is None:
                self._backend = create_backend(enqueue=not self._synchronous)
                self._owner_pid = getpid()
            return self._backend

    def configure(self, *, synchronous: bool = False) -> None:
        """Select delivery before the first log call.

        Parameters
        ----------
        synchronous : bool, default=False
            Write in the calling thread instead of through the Loguru queue.
        """
        with self._lock:
            if self._backend is not None or self._closed:
                raise RuntimeError("Logger configuration is already fixed")
            self._synchronous = synchronous

    def initialize(self) -> None:
        """Create the owner queue before workers start."""
        self._get_backend()

    def __getstate__(self) -> dict[str, object]:
        """Serialize only state needed by a spawned logging worker."""
        if self._synchronous:
            raise ValueError("Worker logging requires queued delivery")
        return {"backend": self._get_backend(), "owner_pid": self._owner_pid}

    def __setstate__(self, state: dict[str, object]) -> None:
        """Restore a queued logger without creating a worker thread."""
        self._backend = cast(LoguruLogger, state["backend"])
        self._lock = RLock()
        self._synchronous = False
        self._owner_pid = cast(int | None, state["owner_pid"])
        self._closed = False

    def flush(self) -> None:
        """Wait until Loguru delivers all queued records."""
        with self._lock:
            if self._backend is not None and not self._closed:
                self._backend.complete()

    def shutdown(self) -> None:
        """Flush queued records and close the owner process handler."""
        with self._lock:
            if self._closed:
                return
            if self._backend is not None:
                self._backend.complete()
                if self._owner_pid == getpid():
                    self._backend.remove()
            self._closed = True

    def _use_worker_backend(self, owner: "Logger") -> None:
        """Use an owner's native Loguru queue in a spawned worker."""
        with self._lock:
            if self._backend is not None or self._closed:
                raise RuntimeError("Worker logger is already initialized")
            if owner._synchronous:
                raise ValueError("Worker logging requires queued delivery")
            self._backend = owner._get_backend()
            self._owner_pid = owner._owner_pid

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
        with self._lock:
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
