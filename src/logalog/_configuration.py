"""Load explicit logging configuration files."""

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from typing import Literal, cast

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


_ROOT_KEYS = frozenset({"synchronous", "prefix", "verbose", "debug", "silent", "modules", "files"})
_CONTROL_KEYS = frozenset({"verbose", "debug", "silent"})
_FILE_KEYS = frozenset(FileDestination.__dataclass_fields__)


@dataclass(frozen=True, slots=True)
class Configuration:
    """Contain validated settings from explicit files."""

    synchronous: bool | None = None
    prefix: str = "LOGALOG"
    verbose: bool = False
    debug: bool = False
    silent: bool = False
    modules: tuple[tuple[str, tuple[bool | None, bool | None, bool | None]], ...] = ()
    files: tuple[FileDestination, ...] = ()

    def __post_init__(self) -> None:
        """Validate controls, including programmatic configuration.

        Raises
        ------
        ConfigurationError
            If a control is not a Boolean or a module name is invalid or repeated.
        """
        # A truthy non-Boolean value could silence or enable output by mistake.
        if (self.synchronous is not None and type(self.synchronous) is not bool) or any(
            type(value) is not bool for value in (self.verbose, self.debug, self.silent)
        ):
            raise ConfigurationError("Delivery and control settings must be Booleans")
        for module, controls in self.modules:
            check_module(module)
            if len(controls) != 3 or any(
                value is not None and type(value) is not bool for value in controls
            ):
                raise ConfigurationError(f"Module {module} controls must be Booleans or None")
        names = [module for module, _ in self.modules]
        if len(names) != len(set(names)):
            raise ConfigurationError("Module names must be unique")


def check_module(module: str) -> None:
    """Reject a module name that cannot form an inheritance path.

    Parameters
    ----------
    module : str
        Full dotted module name.

    Raises
    ------
    ConfigurationError
        If the name or one of its parts is empty.
    """
    if not module or any(not part for part in module.split(".")):
        raise ConfigurationError("Module names must have nonempty dot-separated parts")


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate JSON object keys."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate key: {key}")
        result[key] = value
    return result


def _read(path: Path) -> object:
    """Read one supported document without discovery or interpolation."""
    with path.open("rb") as stream:
        if path.suffix == ".toml":
            from tomllib import load as load_toml

            return load_toml(stream)
        text = stream.read().decode("utf8")
    if path.suffix == ".json":
        return json.loads(text, object_pairs_hook=_pairs)
    if path.suffix in {".yaml", ".yml"}:
        try:
            from ._yaml import load
        except ModuleNotFoundError as error:
            raise ConfigurationError(
                f"{path}: YAML configuration needs the 'logalog[yaml]' extra"
            ) from error
        return load(text)
    raise ValueError("Supported configuration suffixes are .toml, .json, .yaml, and .yml")


def _dict(value: object, source: Path, setting: str) -> Mapping[str, object]:
    """Require a string-keyed mapping."""
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ConfigurationError(f"{source}: {setting} must be a mapping")
    return cast(Mapping[str, object], value)


def _keys(value: Mapping[str, object], allowed: frozenset[str], source: Path, setting: str) -> None:
    """Reject unknown setting names."""
    if unknown := value.keys() - allowed:
        raise ConfigurationError(f"{source}: unknown {setting} setting {sorted(unknown)[0]!r}")


class ConfigurationError(ValueError):
    """Report invalid file or live-control configuration."""


def _bool(value: object, source: Path, setting: str) -> bool:
    """Require a Boolean without integer coercion."""
    if type(value) is not bool:
        raise ConfigurationError(f"{source}: {setting} must be a Boolean")
    return value


def _optional_bool(value: object, source: Path, setting: str) -> bool | None:
    """Require a Boolean or an omitted module control."""
    return _bool(value, source, setting) if value is not None else None


def _files(value: object, source: Path) -> tuple[FileDestination, ...]:
    """Validate file destinations and resolve their paths from their source."""
    if not isinstance(value, list):
        raise ConfigurationError(f"{source}: files must be a list")
    destinations = []
    for index, item in enumerate(value):
        if isinstance(item, FileDestination):
            destinations.append(item)
            continue
        setting = f"files[{index}]"
        data = _dict(item, source, setting)
        _keys(data, _FILE_KEYS, source, setting)
        if not isinstance(data.get("path"), str) or not data["path"]:
            raise ConfigurationError(f"{source}: {setting}.path must be a string")
        values = dict(data)
        values["path"] = source.parent / cast(str, data["path"])
        try:
            destinations.append(FileDestination(**values))  # ty: ignore[invalid-argument-type]
        except ValueError as error:
            raise ConfigurationError(f"{source}: {setting}: {error}") from None
    return tuple(destinations)


def _validate(data: Mapping[str, object], source: Path) -> Configuration:
    """Convert a merged document to strict typed settings."""
    _keys(data, _ROOT_KEYS, source, "configuration")
    prefix = data.get("prefix", "LOGALOG")
    if not isinstance(prefix, str) or re.fullmatch(r"[A-Z][A-Z0-9_]*", prefix) is None:
        raise ConfigurationError(f"{source}: invalid prefix")
    modules_data = _dict(data.get("modules", {}), source, "modules")
    modules = []
    for module, raw_controls in modules_data.items():
        try:
            check_module(module)
        except ConfigurationError as error:
            raise ConfigurationError(f"{source}: {error}") from None
        controls = _dict(raw_controls, source, f"modules.{module}")
        _keys(controls, _CONTROL_KEYS, source, f"modules.{module}")
        modules.append(
            (
                module,
                tuple(
                    _optional_bool(controls.get(name), source, f"modules.{module}.{name}")
                    for name in ("verbose", "debug", "silent")
                ),
            )
        )
    return Configuration(
        synchronous=_optional_bool(data.get("synchronous"), source, "synchronous"),
        prefix=prefix,
        verbose=_bool(data.get("verbose", False), source, "verbose"),
        debug=_bool(data.get("debug", False), source, "debug"),
        silent=_bool(data.get("silent", False), source, "silent"),
        modules=cast(
            tuple[tuple[str, tuple[bool | None, bool | None, bool | None]], ...], tuple(modules)
        ),
        files=_files(data.get("files", []), source),
    )


def _merge(base: dict[str, object], update: Mapping[str, object]) -> dict[str, object]:
    """Merge mappings recursively. Replace lists and scalar values.

    Parameters
    ----------
    base : dict[str, object]
        Earlier settings. This function changes it in place.
    update : Mapping[str, object]
        Later settings, which take priority.

    Returns
    -------
    dict[str, object]
        The merged ``base`` mapping.
    """
    for key, value in update.items():
        if isinstance(value, Mapping):
            current = base.get(key)
            base[key] = _merge(current if isinstance(current, dict) else {}, value)
        else:
            base[key] = value
    return base


def load_configuration(*sources: str | PathLike[str]) -> Configuration:
    """Load explicit files in order, with later values taking priority.

    Parameters
    ----------
    *sources : str or PathLike[str]
        Explicit TOML, JSON, or YAML paths. A file named ``pyproject.toml``
        loads only ``[tool.logalog]``. Relative destination paths use the
        directory of the file that supplies the final ``files`` list.
    """
    merged: dict[str, object] = {}
    last = Path("<defaults>")
    for source in sources:
        path = Path(source).absolute()
        try:
            document = _dict(_read(path), path, "document")
            if path.name == "pyproject.toml":
                document = _dict(
                    _dict(document.get("tool", {}), path, "tool").get("logalog", {}),
                    path,
                    "tool.logalog",
                )
            if "files" in document:
                document = dict(document)
                document["files"] = list(_files(document["files"], path))
            _validate(document, path)
            _merge(merged, document)
            last = path
        except ConfigurationError:
            raise
        # Parser errors are ValueError subclasses.
        except (OSError, UnicodeError, TypeError, ValueError) as error:
            raise ConfigurationError(f"{path}: {error}") from error
    return _validate(merged, last)
