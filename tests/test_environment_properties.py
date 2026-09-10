"""Check reversible module control names across Unicode inputs."""

from hypothesis import given
from hypothesis import strategies as st

from malideiter import environment_names


@given(
    st.lists(
        st.lists(
            st.text(
                alphabet=st.characters(exclude_categories=("Cs",), exclude_characters="."),
                min_size=1,
                max_size=12,
            ),
            min_size=1,
            max_size=4,
        ).map(".".join),
        min_size=1,
        max_size=8,
        unique=True,
    )
)
def test_module_names_are_reversible_and_distinct(modules: list[str]) -> None:
    """Keep Unicode, case, separators, and module boundaries unambiguous."""
    names = [environment_names(module)["module_debug"] for module in modules]
    assert len(set(names)) == len(modules)
    for module, name in zip(modules, names, strict=True):
        encoded = name.removeprefix("MALIDEITER_MODULE__").removesuffix("_DEBUG")
        decoded = ".".join(bytes.fromhex(part).decode("utf-8") for part in encoded.split("__"))
        assert decoded == module
        assert name.isascii()
        assert name == name.upper()
