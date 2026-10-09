"""Provide the typed core logging interface."""

import json
import re
from collections.abc import Callable, Iterable, Sequence
from contextvars import ContextVar, Token
from dataclasses import replace
from functools import cache, partial, wraps
from inspect import currentframe, isasyncgenfunction, iscoroutinefunction, isgeneratorfunction
from os import PathLike, environ, fspath, getpid, register_at_fork
from os import name as os_name
from os.path import basename, normcase, realpath, splitext
from shlex import join as shell_join
from subprocess import list2cmdline
from threading import Condition
from time import monotonic
from types import FunctionType, TracebackType
from typing import Literal, NamedTuple, ParamSpec, TypeVar, cast, overload
from weakref import WeakSet

from loguru._logger import Logger as LoguruLogger
from rich.console import Console, RenderableType
from rich.text import Text

from ._backend import _RICH_SNAPSHOT, FileDestination, close_backend, create_backend
from ._configuration import Configuration, ConfigurationError, check_module

Level = Literal["TRACE", "DEBUG", "VERBOSE", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"]
Control = Literal["verbose", "debug", "silent"]
P = ParamSpec("P")
R = TypeVar("R")

_PREFIX = re.compile(r"[A-Z][A-Z0-9_]*\Z")
_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})
_REDACTED = "[REDACTED]"
_LOGGERS: "WeakSet[Logger]" = WeakSet()


class _Source(NamedTuple):
    """Store stable source data for an asynchronous lifecycle."""

    module: str
    function: str
    path: str
    line: int


def _quote_command(arguments: Sequence[str], *, windows: bool = os_name == "nt") -> str:
    """Quote an argument vector for the selected platform convention."""
    return list2cmdline(arguments) if windows else shell_join(arguments)


class _Section:
    """Manage one logger section without changing exception behavior."""

    def __init__(
        self, logger: "Logger", title: str, elapsed: bool, source: _Source | None = None
    ) -> None:
        self._logger = logger
        self._title = title
        self._elapsed = elapsed
        self._source = source
        self._token: Token[tuple[str, ...]] | None = None
        self._started = 0.0

    def __enter__(self) -> None:
        if self._token is not None:
            raise RuntimeError("Section is already active")
        context = (*self._logger._sections.get(), self._title)
        self._token = self._logger._sections.set(context)
        self._started = monotonic()
        try:
            self._logger._emit("INFO", "▶ {}", (self._title,), {}, source=self._source)
        except BaseException:
            self._logger._sections.reset(self._token)
            self._token = None
            raise

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        token = self._token
        if token is None:
            raise RuntimeError("Section is not active")
        try:
            duration = monotonic() - self._started
            suffix = f" ({duration:.3f} s)" if self._elapsed else ""
            failed = exception_type is not None
            self._logger._emit(
                "ERROR" if failed else "SUCCESS",
                "✗ {}{}" if failed else "✓ {}{}",
                (self._title, suffix),
                {},
                exception=failed,
                source=self._source,
            )
        except BaseException:
            if exception_type is None:
                raise
        finally:
            self._logger._sections.reset(token)
            self._token = None
        return False


@cache
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


def environment_names(module: str, *, prefix: str = "LOGALOG") -> dict[str, str]:
    """Return the global and exact-module environment variable names.

    Parameters
    ----------
    module : str
        Full caller module name.
    prefix : str, default="LOGALOG"
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


def _validate(module: str, prefix: str) -> None:
    """Validate values that form environment variable names."""
    check_module(module)
    if _PREFIX.fullmatch(prefix) is None:
        raise ValueError("Prefix must contain uppercase ASCII letters, digits, or underscores")


def _boolean(name: str, value: str) -> bool:
    """Parse a deterministic environment Boolean."""
    normalized = value.strip().lower()
    if normalized in _TRUE:
        return True
    if normalized in _FALSE:
        return False
    raise ConfigurationError(f"Invalid Boolean value for {name}")


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
        stored = (
            defaults
            if scope_index == 0
            else module_defaults.get(".".join(module_parts[:scope_index]), (None, None, None))
        )
        for index, name in enumerate(scope):
            raw = environ.get(name)
            enabled = _boolean(name, raw) if raw is not None else stored[index]
            if enabled is not None:
                if index == 2:
                    values[index] |= enabled
                else:
                    values[index] = enabled
    return cast(tuple[bool, bool, bool], tuple(values))


def _file_path(destination: FileDestination) -> str:
    """Check each destination type and resolve its path for duplicate detection."""
    if not isinstance(destination, FileDestination):
        raise TypeError("Each file destination must be a FileDestination")
    path = fspath(destination.path)
    if not path:
        raise ValueError("File path must not be empty")
    return normcase(realpath(path))


def _validate_files(files: tuple[FileDestination, ...]) -> None:
    """Reject empty and repeated paths before backend setup."""
    paths = [_file_path(destination) for destination in files]
    if len(paths) != len(set(paths)):
        raise ValueError("File destination paths must be unique")


class Logger:
    """Send typed log calls to an isolated, lazily initialized backend."""

    def __init__(
        self,
        *,
        synchronous: bool = False,
        prefix: str = "LOGALOG",
        files: tuple[FileDestination, ...] = (),
    ) -> None:
        """Keep import free of output and worker threads."""
        _validate("module", prefix)
        _validate_files(files)
        self._backend: LoguruLogger | None = None
        self._lock = Condition()
        self._active = 0
        self._synchronous = synchronous
        self._prefix = prefix
        self._files = files
        self._control_defaults = (False, False, False)
        self._module_defaults: dict[str, tuple[bool | None, bool | None, bool | None]] = {}
        self._owner_pid: int | None = None
        self._closed = False
        self._renderer: Console | None = None
        self._sections: ContextVar[tuple[str, ...]] = ContextVar(
            f"logalog_sections_{id(self)}", default=()
        )
        _LOGGERS.add(self)

    def _reset_after_fork(self) -> None:
        """Give a forked child an unlocked lock and no inherited active calls."""
        self._lock = Condition()
        self._active = 0

    def _get_backend(self, *, accepted: bool = False) -> LoguruLogger:
        """Initialize the backend once, including during concurrent first use.

        Parameters
        ----------
        accepted : bool, default=False
            Permit a call that was accepted before shutdown started.
        """
        with self._lock:
            if self._closed and not accepted:
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
        self._sections = ContextVar(f"logalog_sections_{id(self)}", default=())
        self._lock = Condition()
        self._active = 0
        _LOGGERS.add(self)

    def flush(self) -> None:
        """Wait until the queue delivers all accepted records.

        File objects keep their configured buffering. Shutdown closes and flushes them.
        """
        with self._lock:
            backend = None if self._closed else self._backend
        if backend is not None:
            backend.complete()

    def shutdown(self) -> None:
        """Finish accepted calls, flush queued records, and close the owner handlers.

        Raises
        ------
        Exception
            The first failure from a handler that closed. All handlers still close.
        """
        with self._lock:
            if self._closed:
                return
            self._closed = True
            while self._active:
                self._lock.wait()
            backend = self._backend
        if backend is not None:
            backend.complete()
            if self._owner_pid == getpid():
                close_backend(backend)

    def _close_at_exit(self) -> None:
        """Flush and close at interpreter exit, then accept later exit records.

        Exit handlers that ran before import can still log. Those records use
        synchronous delivery. The owner reopens its files in append mode.
        """
        try:
            self.shutdown()
        finally:
            with self._lock:
                owner = self._owner_pid in {None, getpid()}
                self._files = (
                    tuple(replace(file, mode="a", delay=True) for file in self._files)
                    if owner
                    else ()
                )
                self._synchronous = True
                self._backend = None
                self._closed = False

    def _use_worker_backend(self, owner: "Logger") -> None:
        """Use an owner's native Loguru queue in a worker process."""
        if owner._synchronous or owner._backend is None:
            raise ValueError("Worker logging requires an initialized owner with queued delivery")
        if self is owner:
            return
        with self._lock:
            if self._backend is not None or self._closed:
                raise RuntimeError("Worker logger is already initialized")
            self._backend = owner._backend
            self._owner_pid = owner._owner_pid
            self._prefix = owner._prefix
            self._files = ()
            self._control_defaults = owner._control_defaults
            self._module_defaults = owner._module_defaults

    @overload
    def __call__(self, function: Callable[P, R], /) -> Callable[P, R]: ...

    @overload
    def __call__(self, *, elapsed: bool = False) -> Callable[[Callable[P, R]], Callable[P, R]]: ...

    def __call__(
        self, function: Callable[P, R] | None = None, /, *, elapsed: bool = False
    ) -> Callable[P, R] | Callable[[Callable[P, R]], Callable[P, R]]:
        """Log entry and exit for an ordinary synchronous or asynchronous function.

        Parameters
        ----------
        function : Callable[P, R] or None, default=None
            Function to decorate. Generators and asynchronous generators are not supported.
        elapsed : bool, default=False
            Add monotonic elapsed time to the completion or failure event.
        """
        if function is None:
            return lambda selected: self._decorate(selected, elapsed=elapsed)
        return self._decorate(function, elapsed=elapsed)

    def _decorate(self, function: Callable[P, R], *, elapsed: bool) -> Callable[P, R]:
        """Build the matching synchronous or asynchronous wrapper."""
        if isinstance(function, (classmethod, staticmethod)):
            # Accept @LOG above @classmethod or @staticmethod as well as below.
            method = cast(Callable[P, R], function.__func__)
            return cast(Callable[P, R], type(function)(self._decorate(method, elapsed=elapsed)))
        if isgeneratorfunction(function) or isasyncgenfunction(function):
            raise TypeError("LOG does not support generator functions")
        name = getattr(function, "__qualname__", type(function).__qualname__)
        if iscoroutinefunction(function):
            target = function
            while isinstance(target, partial):
                target = target.func
            code = cast(FunctionType, target).__code__
            source = _Source(
                cast(str, getattr(target, "__module__", "__main__")),
                code.co_name,
                code.co_filename,
                code.co_firstlineno,
            )

            @wraps(function)
            async def asynchronous(*args: P.args, **kwargs: P.kwargs) -> R:
                with _Section(self, name, elapsed, source):
                    return await function(*args, **kwargs)

            return cast(Callable[P, R], asynchronous)

        @wraps(function)
        def synchronous(*args: P.args, **kwargs: P.kwargs) -> R:
            with self.section(name, elapsed=elapsed):
                return function(*args, **kwargs)

        return synchronous

    def section(self, title: str, *, elapsed: bool = False) -> _Section:
        """Return a recursively indented logging section.

        Parameters
        ----------
        title : str
            Section identity shown in lifecycle events and structured metadata.
        elapsed : bool, default=False
            Add monotonic elapsed time to the completion or failure event.
        """
        if not title:
            raise ValueError("Section title must not be empty")
        return _Section(self, title, elapsed)

    def command(
        self,
        arguments: Sequence[str],
        *,
        redact_indices: Iterable[int] = (),
        redact_values: Iterable[str] = (),
        cwd: str | PathLike[str] | None = None,
    ) -> None:
        """Display a platform-quoted command without executing it.

        Parameters
        ----------
        arguments : Sequence[str]
            Command argument vector.
        redact_indices : Iterable[int], default=()
            Zero-based argument positions to replace before logging.
        redact_values : Iterable[str], default=()
            Exact argument values to replace before logging.
        cwd : str or PathLike[str] or None, default=None
            Planned working directory to display without changing directories.
        """
        if isinstance(arguments, (str, bytes)) or not arguments:
            raise ValueError("Command arguments must be a nonempty sequence")
        if any(not isinstance(argument, str) for argument in arguments):
            raise TypeError("Every command argument must be a string")
        indices = tuple(redact_indices)
        if any(isinstance(index, bool) or not isinstance(index, int) for index in indices):
            raise TypeError("Every redaction index must be an integer")
        if any(index < 0 or index >= len(arguments) for index in indices):
            raise IndexError("Command redaction index is out of range")
        if isinstance(redact_values, str):
            raise TypeError("Give redact_values as a collection of strings, not one string")
        values = tuple(redact_values)
        if any(not isinstance(value, str) for value in values):
            raise TypeError("Every redaction value must be a string")
        hidden = set(values)
        displayed = [
            _REDACTED if index in indices or argument in hidden else argument
            for index, argument in enumerate(arguments)
        ]
        quoted = _quote_command(displayed)
        displayed_cwd = None if cwd is None else fspath(cwd)
        if displayed_cwd in hidden:
            displayed_cwd = _REDACTED
        if displayed_cwd is None:
            self.info("$ {}", quoted, command=tuple(displayed))
        else:
            self.info(
                "$ {}\n  cwd: {}",
                quoted,
                _quote_command([displayed_cwd]),
                command=tuple(displayed),
                cwd=displayed_cwd,
            )

    def _emit(
        self,
        level: Level,
        message: RenderableType,
        args: tuple[object, ...],
        fields: dict[str, object],
        *,
        exception: bool = False,
        source: _Source | None = None,
    ) -> None:
        """Preserve the external caller through library frames."""
        frame = currentframe()
        depth = 0
        try:
            while frame is not None and frame.f_globals.get("__name__", "").startswith("logalog."):
                depth += 1
                frame = frame.f_back
            module = (
                source.module
                if source
                else (
                    cast(str, frame.f_globals.get("__name__", "__main__")) if frame else "__main__"
                )
            )
        finally:
            del frame

        verbose, debug, silent = _controls(
            module, self._prefix, self._control_defaults, self._module_defaults
        )
        if (
            silent
            or (level == "VERBOSE" and not verbose)
            or (level in {"DEBUG", "TRACE"} and not debug)
        ):
            if self._closed:
                raise RuntimeError("Logger is shut down")
            return

        # Count the accepted call so that shutdown waits for it without a held lock.
        with self._lock:
            if self._closed:
                raise RuntimeError("Logger is shut down")
            self._active += 1
        try:
            # Also skip the delivery frame.
            self._deliver(level, message, args, fields, depth + 1, exception, source)
        finally:
            with self._lock:
                self._active -= 1
                if not self._active:
                    self._lock.notify_all()

    def _deliver(
        self,
        level: Level,
        message: RenderableType,
        args: tuple[object, ...],
        fields: dict[str, object],
        depth: int,
        exception: bool,
        source: _Source | None,
    ) -> None:
        """Format, render, and submit one accepted event."""
        if isinstance(message, str) and (args or fields):
            message = message.format(*args, **fields)
            args = ()
        sections = self._sections.get()
        indentation = "  " * (len(sections) - 1) if sections else ""
        if sections:
            fields |= {
                "section_depth": len(sections),
                "section": sections[-1],
                "section_parent": sections[-2] if len(sections) > 1 else None,
            }
            if isinstance(message, str):
                message = indentation + message.replace("\n", f"\n{indentation}")
        if fields and any(destination.kind == "json" for destination in self._files):
            # Reject fields that JSON cannot encode before any destination accepts the event.
            json.dumps(fields, default=str)

        if not isinstance(message, str):
            if args:
                raise ValueError("Rich renderables do not accept format arguments")
            if self._renderer is None:
                self._renderer = Console(stderr=True, markup=False, highlight=False)
            options = self._renderer.options
            if sections:
                options = options.update_width(max(1, options.max_width - len(indentation)))
            snapshot = Text.assemble(
                *(
                    (segment.text, segment.style) if segment.style else segment.text
                    for segment in self._renderer.render(message, options)
                )
            )
            if sections:
                if snapshot.plain.endswith("\n"):
                    snapshot = snapshot[:-1]
                snapshot = Text(indentation) + Text(f"\n{indentation}").join(
                    snapshot.split(allow_blank=True)
                )
            message = snapshot.plain.removesuffix("\n")
            fields[_RICH_SNAPSHOT] = snapshot
        backend = self._backend or self._get_backend(accepted=True)
        if source is not None:
            backend = backend.patch(
                lambda record: record.update(
                    name=source.module,
                    function=source.function,
                    file=type(record["file"])(basename(source.path), source.path),
                    module=splitext(basename(source.path))[0],
                    line=source.line,
                )
            )
        backend.bind(**fields).opt(depth=depth, exception=exception).log(level, message)

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


def _reset_after_fork() -> None:
    """Release logger locks that another parent thread held during ``fork``."""
    for logger in list(_LOGGERS):
        logger._reset_after_fork()


register_at_fork(after_in_child=_reset_after_fork)
