"""Load YAML configuration with a strict safe loader.

The configuration loader imports this module only for YAML paths.
"""

import re

import yaml
from yaml.constructor import ConstructorError
from yaml.resolver import BaseResolver


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


def load(text: str) -> object:
    """Parse one YAML document without unsafe tags or duplicate keys.

    Parameters
    ----------
    text : str
        YAML document text.

    Returns
    -------
    object
        Parsed document.

    Raises
    ------
    ValueError
        If the document is not valid for the strict loader.
    """
    try:
        # The private SafeLoader subclass also rejects duplicate keys.
        return yaml.load(text, Loader=_UniqueSafeLoader)  # noqa: S506 # nosec B506
    except yaml.YAMLError as error:
        raise ValueError(str(error)) from error
