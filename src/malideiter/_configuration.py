"""Load explicit logging configuration files."""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from tomllib import TOMLDecodeError
from tomllib import load as load_toml
from typing import cast

import yaml
from beartype import beartype
from configurator import Config
from configurator.merge import merge_dict
from yaml.constructor import ConstructorError
from yaml.resolver import BaseResolver

from ._backend import FileDestination

_ROOT_KEYS = frozenset({"synchronous", "prefix", "verbose", "debug", "silent", "modules", "files"})
_CONTROL_KEYS = frozenset({"verbose", "debug", "silent"})
_FILE_KEYS = frozenset(FileDestination.__dataclass_fields__)
_KINDS = frozenset({"text", "json"})
_COMPRESSIONS = frozenset({"gz", "bz2", "xz", "lzma", "tar", "tar.gz", "tar.bz2", "tar.xz", "zip"})


class _UniqueSafeLoader(yaml.SafeLoader):
    """Reject duplicate YAML mapping keys."""


@beartype
def _mapping(loader: _UniqueSafeLoader, node: yaml.Node) -> dict[object, object]:
    """Build one safe YAML mapping with unique keys."""
    if not isinstance(node, yaml.MappingNode):
        raise ConstructorError(None, None, "Expected a mapping node", node.start_mark)
    result: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=False)
        if key in result:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "duplicate key",
                key_node.start_mark,
            )
        result[key] = loader.construct_object(value_node, deep=True)
    return result


_UniqueSafeLoader.add_constructor(
    BaseResolver.DEFAULT_MAPPING_TAG,
    _mapping,
)


@beartype
@dataclass(frozen=True, slots=True)
class Configuration:
    """Contain validated settings from explicit files."""

    synchronous: bool = False
    prefix: str = "MALIDEITER"
    verbose: bool = False
    debug: bool = False
    silent: bool = False
    modules: tuple[tuple[str, tuple[bool | None, bool | None, bool | None]], ...] = ()
    files: tuple[FileDestination, ...] = ()

    def __post_init__(self) -> None:
        """Validate every module entry, including programmatic configuration."""
        names = [_module_name(entry) for entry in self.modules]
        if len(names) != len(set(names)):
            raise ConfigurationError("Module names must be unique")


@beartype
def _module_name(entry: tuple[str, tuple[bool | None, bool | None, bool | None]]) -> str:
    """Check a complete module entry without sampled outer-container validation."""
    module = entry[0]
    if not module or any(not part for part in module.split(".")):
        raise ConfigurationError("Module names must have nonempty parts")
    return module


@beartype
def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate JSON object keys."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate key: {key}")
        result[key] = value
    return result


@beartype
def _read(path: Path) -> object:
    """Read one supported document without discovery or interpolation."""
    with path.open("rb") as stream:
        if path.suffix == ".toml":
            return load_toml(stream)
        text = stream.read().decode("utf8")
    if path.suffix == ".json":
        return json.loads(text, object_pairs_hook=_pairs)
    if path.suffix in {".yaml", ".yml"}:
        # The private SafeLoader subclass also rejects duplicate keys.
        return yaml.load(text, Loader=_UniqueSafeLoader)  # noqa: S506 # nosec B506
    raise ValueError("Supported configuration suffixes are .toml, .json, .yaml, and .yml")


@beartype
def _dict(value: object, source: Path, setting: str) -> Mapping[str, object]:
    """Require a string-keyed mapping."""
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ConfigurationError(f"{source}: {setting} must be a mapping")
    return cast(Mapping[str, object], value)


@beartype
def _keys(value: Mapping[str, object], allowed: frozenset[str], source: Path, setting: str) -> None:
    """Reject unknown setting names."""
    if unknown := value.keys() - allowed:
        raise ConfigurationError(f"{source}: unknown {setting} setting {sorted(unknown)[0]!r}")


class ConfigurationError(ValueError):
    """Report invalid file or live-control configuration."""


@beartype
def _bool(value: object, source: Path, setting: str) -> bool:
    """Require a Boolean without integer coercion."""
    if type(value) is not bool:
        raise ConfigurationError(f"{source}: {setting} must be a Boolean")
    return value


@beartype
def _optional_bool(value: object, source: Path, setting: str) -> bool | None:
    """Require a Boolean or an omitted module control."""
    return _bool(value, source, setting) if value is not None else None


@beartype
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
        checks = {
            "kind": lambda item: isinstance(item, str) and item in _KINDS,
            "rotation": lambda item: item is None or type(item) in {str, int},
            "retention": lambda item: item is None or type(item) in {str, int},
            "compression": lambda item: (
                item is None or (isinstance(item, str) and item in _COMPRESSIONS)
            ),
            "delay": lambda item: type(item) is bool,
            "watch": lambda item: type(item) is bool,
            "mode": lambda item: isinstance(item, str) and item in {"a", "w"},
            "encoding": lambda item: type(item) is str,
            "buffering": lambda item: type(item) is int,
        }
        if invalid := next(
            (name for name, check in checks.items() if name in data and not check(data[name])), None
        ):
            raise ConfigurationError(f"{source}: invalid {setting}.{invalid}")
        values = dict(data)
        values["path"] = source.parent / cast(str, data["path"])
        destinations.append(FileDestination(**values))  # ty: ignore[invalid-argument-type]
    return tuple(destinations)


@beartype
def _validate(data: Mapping[str, object], source: Path) -> Configuration:
    """Convert a merged document to strict typed settings."""
    _keys(data, _ROOT_KEYS, source, "configuration")
    prefix = data.get("prefix", "MALIDEITER")
    if not isinstance(prefix, str) or re.fullmatch(r"[A-Z][A-Z0-9_]*", prefix) is None:
        raise ConfigurationError(f"{source}: invalid prefix")
    modules_data = _dict(data.get("modules", {}), source, "modules")
    modules = []
    for module, raw_controls in modules_data.items():
        if not module or any(not part for part in module.split(".")):
            raise ConfigurationError(f"{source}: module names must have nonempty parts")
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
        synchronous=_bool(data.get("synchronous", False), source, "synchronous"),
        prefix=prefix,
        verbose=_bool(data.get("verbose", False), source, "verbose"),
        debug=_bool(data.get("debug", False), source, "debug"),
        silent=_bool(data.get("silent", False), source, "silent"),
        modules=cast(
            tuple[tuple[str, tuple[bool | None, bool | None, bool | None]], ...], tuple(modules)
        ),
        files=_files(data.get("files", []), source),
    )


@beartype
def load_configuration(*sources: str | PathLike[str]) -> Configuration:
    """Load explicit files in order, with later values taking priority.

    Parameters
    ----------
    *sources : str or PathLike[str]
        Explicit TOML, JSON, or YAML paths. A file named ``pyproject.toml``
        loads only ``[tool.malideiter]``. Relative destination paths use the
        directory of the file that supplies the final ``files`` list.
    """
    merged = Config({})
    last = Path("<defaults>")
    for source in sources:
        path = Path(source).absolute()
        try:
            document = _dict(_read(path), path, "document")
            if path.name == "pyproject.toml":
                document = _dict(
                    _dict(document.get("tool", {}), path, "tool").get("malideiter", {}),
                    path,
                    "tool.malideiter",
                )
            if "files" in document:
                document = dict(document)
                document["files"] = list(_files(document["files"], path))
            _validate(document, path)
            merged.merge(document, mergers={dict: merge_dict})
            last = path
        except ConfigurationError:
            raise
        except (
            OSError,
            UnicodeError,
            TOMLDecodeError,
            json.JSONDecodeError,
            yaml.YAMLError,
            TypeError,
            ValueError,
        ) as error:
            raise ConfigurationError(f"{path}: {error}") from error
    return _validate(merged.data, last)
