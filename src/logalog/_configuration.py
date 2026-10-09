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
from configurator import Config
from configurator.merge import merge_dict
from yaml.constructor import ConstructorError
from yaml.resolver import BaseResolver

from ._backend import FileDestination

_ROOT_KEYS = frozenset({"synchronous", "prefix", "verbose", "debug", "silent", "modules", "files"})
_CONTROL_KEYS = frozenset({"verbose", "debug", "silent"})
_FILE_KEYS = frozenset(FileDestination.__dataclass_fields__)


class _UniqueSafeLoader(yaml.SafeLoader):
    """Reject duplicate YAML mapping keys."""


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
# Use YAML 1.2 Booleans. YAML 1.1 also reads values such as on, off, yes, and no as Booleans.
_BOOL_TAG = "tag:yaml.org,2002:bool"
_UniqueSafeLoader.yaml_implicit_resolvers = {
    first: [(tag, pattern) for tag, pattern in resolvers if tag != _BOOL_TAG]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_UniqueSafeLoader.add_implicit_resolver(
    _BOOL_TAG, re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF")
)


@dataclass(frozen=True, slots=True)
class Configuration:
    """Contain validated settings from explicit files."""

    synchronous: bool = False
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
        if any(
            type(value) is not bool
            for value in (self.synchronous, self.verbose, self.debug, self.silent)
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
            return load_toml(stream)
        text = stream.read().decode("utf8")
    if path.suffix == ".json":
        return json.loads(text, object_pairs_hook=_pairs)
    if path.suffix in {".yaml", ".yml"}:
        # The private SafeLoader subclass also rejects duplicate keys.
        return yaml.load(text, Loader=_UniqueSafeLoader)  # noqa: S506 # nosec B506
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


def load_configuration(*sources: str | PathLike[str]) -> Configuration:
    """Load explicit files in order, with later values taking priority.

    Parameters
    ----------
    *sources : str or PathLike[str]
        Explicit TOML, JSON, or YAML paths. A file named ``pyproject.toml``
        loads only ``[tool.logalog]``. Relative destination paths use the
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
                    _dict(document.get("tool", {}), path, "tool").get("logalog", {}),
                    path,
                    "tool.logalog",
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
