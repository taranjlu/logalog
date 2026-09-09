"""Provide the typed core logging interface."""

import re
from functools import cache
from inspect import currentframe
from os import environ, fspath, getpid
from os.path import normcase, realpath
from threading import RLock
from typing import Literal, cast

from beartype import beartype
from loguru._logger import Logger as LoguruLogger
from rich.console import Console, RenderableType
from rich.text import Text

from ._backend import _CONSOLE_ONLY, _RICH_PLAIN, _RICH_SNAPSHOT, FileDestination, create_backend
from ._configuration import Configuration, ConfigurationError

Level = Literal["TRACE", "DEBUG", "VERBOSE", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"]
Control = Literal["verbose", "debug", "silent"]

_PREFIX = re.compile(r"[A-Z][A-Z0-9_]*\Z")
_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})


@cache
@beartype
def _control_names(module: str, prefix: str) -> tuple[tuple[str, str, str], ...]:
    """Cache stable environment names for a module and its parents."""
    parts = module.split(".")
    paths = (
        "__".join(part.encode().hex().upper() for part in parts[:end])
        for end in range(1, len(parts) + 1)
    )
    global_names = (f"{prefix}_VERBOSE", f"{prefix}_DEBUG", f"{prefix}_SILENT")
    module_names = tuple(
        (
            f"{prefix}_MODULE__{path}_VERBOSE",
            f"{prefix}_MODULE__{path}_DEBUG",
            f"{prefix}_MODULE__{path}_SILENT",
        )
        for path in paths
    )
    return (global_names, *module_names)


@beartype
def environment_names(module: str, *, prefix: str = "MALIDEITER") -> dict[str, str]:
    """Return the global and exact-module environment variable names.

    Parameters
    ----------
    module : str
        Full caller module name.
    prefix : str, default="MALIDEITER"
        Uppercase application prefix.
    """
    _validate(module, prefix)
    exact = _control_names(module, prefix)[-1]
    return {
        f"global_{control}": f"{prefix}_{control.upper()}"
        for control in ("verbose", "debug", "silent")
    } | {
        f"module_{control}": name
        for control, name in zip(("verbose", "debug", "silent"), exact, strict=True)
    }


@beartype
def _validate(module: str, prefix: str) -> None:
    """Validate values that form environment variable names."""
    if not module or any(not part for part in module.split(".")):
        raise ValueError("Module must contain nonempty dot-separated parts")
    if _PREFIX.fullmatch(prefix) is None:
        raise ValueError("Prefix must contain uppercase ASCII letters, digits, or underscores")


@beartype
def _boolean(name: str, value: str) -> bool:
    """Parse a deterministic environment Boolean."""
    normalized = value.strip().lower()
    if normalized in _TRUE:
        return True
    if normalized in _FALSE:
        return False
    raise ConfigurationError(f"Invalid Boolean value for {name}")


@beartype
def _controls(
    module: str,
    prefix: str,
    defaults: tuple[bool, bool, bool],
    module_defaults: dict[str, tuple[bool | None, bool | None, bool | None]],
) -> tuple[bool, bool, bool]:
    """Read and resolve all live controls for one call."""
    values = [defaults[0], defaults[1], False]
    module_parts = module.split(".")
    for scope_index, scope in enumerate(_control_names(module, prefix)):
        scope_silent = defaults[2] if scope_index == 0 else False
        if scope_index and (stored := module_defaults.get(".".join(module_parts[:scope_index]))):
            for index, enabled in enumerate(stored):
                if enabled is not None:
                    if index == 2:
                        scope_silent = enabled
                    else:
                        values[index] = enabled
        for index, name in enumerate(scope):
            if (value := environ.get(name)) is not None:
                enabled = _boolean(name, value)
                if index == 2:
                    scope_silent = enabled
                else:
                    values[index] = enabled
        values[2] |= scope_silent
    return cast(tuple[bool, bool, bool], tuple(values))


@beartype
def _file_path(destination: FileDestination) -> str:
    """Check each destination type and resolve its path for duplicate detection."""
    path = fspath(destination.path)
    if not path:
        raise ValueError("File path must not be empty")
    return normcase(realpath(path))


@beartype
def _validate_files(files: tuple[FileDestination, ...]) -> None:
    """Reject empty and repeated paths before backend setup."""
    paths = [_file_path(destination) for destination in files]
    if len(paths) != len(set(paths)):
        raise ValueError("File destination paths must be unique")


@beartype
class Logger:
    """Send typed log calls to an isolated, lazily initialized backend."""

    def __init__(
        self,
        *,
        synchronous: bool = False,
        prefix: str = "MALIDEITER",
        files: tuple[FileDestination, ...] = (),
    ) -> None:
        """Keep import free of output and worker threads."""
        _validate("module", prefix)
        _validate_files(files)
        self._backend: LoguruLogger | None = None
        self._lock = RLock()
        self._synchronous = synchronous
        self._prefix = prefix
        self._files = files
        self._control_defaults = (False, False, False)
        self._module_defaults: dict[str, tuple[bool | None, bool | None, bool | None]] = {}
        self._owner_pid: int | None = None
        self._closed = False
        self._renderer: Console | None = None

    def _get_backend(self) -> LoguruLogger:
        """Initialize the backend once, including during concurrent first use."""
        with self._lock:
            if self._closed:
                raise RuntimeError("Logger is shut down")
            if self._backend is None:
                self._backend = create_backend(enqueue=not self._synchronous, files=self._files)
                self._owner_pid = getpid()
            return self._backend

    def configure(
        self,
        *,
        configuration: Configuration | None = None,
        synchronous: bool | None = None,
        prefix: str | None = None,
        files: tuple[FileDestination, ...] | None = None,
    ) -> None:
        """Select delivery before the first log call.

        Parameters
        ----------
        configuration : Configuration or None, default=None
            Stored settings loaded by :func:`load_configuration`.
        synchronous : bool or None, default=None
            Write in the calling thread instead of through the Loguru queue.
        prefix : str or None, default=None
            Uppercase prefix for live control environment variables.
        files : tuple[FileDestination, ...] or None, default=None
            Text and JSON Lines destinations.
        """
        selected = configuration or Configuration()
        synchronous = selected.synchronous if synchronous is None else synchronous
        prefix = selected.prefix if prefix is None else prefix
        files = selected.files if files is None else files
        _validate("module", prefix)
        _validate_files(files)
        module_defaults = dict(selected.modules)
        with self._lock:
            if self._backend is not None or self._closed:
                raise RuntimeError("Logger configuration is already fixed")
            self._synchronous = synchronous
            self._prefix = prefix
            self._files = files
            self._control_defaults = (selected.verbose, selected.debug, selected.silent)
            self._module_defaults = module_defaults

    def initialize(self) -> None:
        """Create the owner queue before workers start."""
        self._get_backend()

    def __getstate__(self) -> dict[str, object]:
        """Serialize only state needed by a spawned logging worker."""
        if self._synchronous:
            raise ValueError("Worker logging requires queued delivery")
        return {
            "backend": self._get_backend(),
            "owner_pid": self._owner_pid,
            "prefix": self._prefix,
            "control_defaults": self._control_defaults,
            "module_defaults": self._module_defaults,
        }

    def __setstate__(self, state: dict[str, object]) -> None:
        """Restore a queued logger without creating a worker thread."""
        self._backend = cast(LoguruLogger, state["backend"])
        self._lock = RLock()
        self._synchronous = False
        self._prefix = cast(str, state["prefix"])
        self._files = ()
        self._control_defaults = cast(tuple[bool, bool, bool], state["control_defaults"])
        self._module_defaults = cast(
            dict[str, tuple[bool | None, bool | None, bool | None]], state["module_defaults"]
        )
        self._owner_pid = cast(int | None, state["owner_pid"])
        self._closed = False
        self._renderer = None

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
            self._prefix = owner._prefix
            self._files = ()
            self._control_defaults = owner._control_defaults
            self._module_defaults = owner._module_defaults

    def _emit(
        self,
        level: Level,
        message: RenderableType,
        args: tuple[object, ...],
        fields: dict[str, object],
        *,
        exception: bool = False,
    ) -> None:
        """Preserve the external caller through library and Beartype wrappers."""
        with self._lock:
            if self._closed:
                raise RuntimeError("Logger is shut down")
            frame = currentframe()
            depth = 0
            try:
                while frame is not None and (
                    frame.f_globals.get("__name__", "").startswith("malideiter.")
                    or frame.f_code.co_filename.startswith("<@beartype(malideiter.")
                ):
                    depth += 1
                    frame = frame.f_back
                module = (
                    cast(str, frame.f_globals.get("__name__", "__main__")) if frame else "__main__"
                )
            finally:
                del frame

            verbose, debug, silent = _controls(
                module, self._prefix, self._control_defaults, self._module_defaults
            )
            if silent or (level == "VERBOSE" and not verbose) or (level == "DEBUG" and not debug):
                return

            if not isinstance(message, str):
                if args:
                    raise ValueError("Rich renderables do not accept format arguments")
                if self._renderer is None:
                    self._renderer = Console(stderr=True, markup=False, highlight=False)
                snapshot = Text.assemble(
                    *(
                        (segment.text, segment.style) if segment.style else segment.text
                        for segment in self._renderer.render(message)
                    )
                )
                message = snapshot.plain.removesuffix("\n")
                fields[_RICH_SNAPSHOT] = snapshot
            backend = self._get_backend()
            if _RICH_SNAPSHOT in fields:
                backend.bind(**fields).opt(depth=depth, exception=exception).log(level, message)
                fields.pop(_RICH_SNAPSHOT)
                fields[_RICH_PLAIN] = True
                backend.bind(**fields).opt(depth=depth, exception=exception).log(level, message)
                return
            if exception:
                if args or fields:
                    message = message.format(*args, **fields)
                backend.bind(**fields, **{_CONSOLE_ONLY: True}).opt(
                    depth=depth, exception=True
                ).log(level, message)
                backend.bind(**fields, **{_RICH_PLAIN: True}).opt(depth=depth, exception=True).log(
                    level, message
                )
                return
            backend.opt(depth=depth, exception=exception).log(level, message, *args, **fields)

    def log(self, level: Level, message: RenderableType, *args: object, **fields: object) -> None:
        """Log a message at a supported severity.

        Parameters
        ----------
        level : Level
            Standard Loguru severity name.
        message : RenderableType
            Literal text, a format template, or a Rich renderable.
        *args : object
            Positional format arguments.
        **fields : object
            Named format arguments, also retained as Loguru record data.
        """
        self._emit(level, message, args, fields)

    def trace(self, message: RenderableType, *args: object, **fields: object) -> None:
        """Log a trace message."""
        self._emit("TRACE", message, args, fields)

    def debug(self, message: RenderableType, *args: object, **fields: object) -> None:
        """Log a debug message."""
        self._emit("DEBUG", message, args, fields)

    def verbose(self, message: RenderableType, *args: object, **fields: object) -> None:
        """Log a verbose message."""
        self._emit("VERBOSE", message, args, fields)

    def info(self, message: RenderableType, *args: object, **fields: object) -> None:
        """Log an information message."""
        self._emit("INFO", message, args, fields)

    def success(self, message: RenderableType, *args: object, **fields: object) -> None:
        """Log a success message."""
        self._emit("SUCCESS", message, args, fields)

    def warning(self, message: RenderableType, *args: object, **fields: object) -> None:
        """Log a warning message."""
        self._emit("WARNING", message, args, fields)

    def error(self, message: RenderableType, *args: object, **fields: object) -> None:
        """Log an error message without an automatic traceback."""
        self._emit("ERROR", message, args, fields)

    def critical(self, message: RenderableType, *args: object, **fields: object) -> None:
        """Log a critical message."""
        self._emit("CRITICAL", message, args, fields)

    def exception(self, message: RenderableType, *args: object, **fields: object) -> None:
        """Log an error with the currently handled exception, without locals."""
        self._emit("ERROR", message, args, fields, exception=True)
