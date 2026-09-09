set default-list := true

# Check formatting, lint rules, and types.
check:
    uv run ruff format --check .
    uv run ruff check .
    uv run ty check

# Run the tests.
test:
    uv run pytest

# Apply formatting and safe lint fixes.
fix:
    uv run ruff format .
    uv run ruff check . --fix

# Build the wheel and source distribution.
build:
    uv build --no-sources
