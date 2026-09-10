set default-list := true

# Run static analysis and runtime dependency security checks.
check: lint security

# Check formatting, types, complexity, dependencies, and unused code.
lint:
    uv run ruff format --check .
    uv run ruff check .
    uv run ty check
    uv run complexipy
    uv run deptry src
    uv run vulture

# Scan source and audit locked runtime dependencies (requires network access).
security:
    #!/usr/bin/env bash
    set -euo pipefail
    uv run bandit -r src -ll -ii
    requirements="$(mktemp)"
    trap 'rm -f "$requirements"' EXIT
    uv export --no-dev --no-emit-project --locked --output-file "$requirements" >/dev/null
    uv run pip-audit --requirement "$requirements" --disable-pip

# Show test names in specification format without Sugar.
test-spec:
    uv run pytest --spec -p no:sugar

# Repeat randomized test order with a recorded seed.
test-random seed:
    uv run pytest --randomly-seed={{quote(seed)}}

# Run the tests.
test:
    uv run pytest

# Run the focused image regression checks.
test-images:
    uv run pytest --no-cov tests/test_visual.py

# Write an HTML coverage report to htmlcov/index.html.
coverage:
    uv run pytest --cov-report=html

# Run the test suite on every supported Python version.
matrix:
    uv run nox

# Alias for the Python test matrix.
test-matrix: matrix

# Apply formatting and safe lint fixes.
fix:
    uv run ruff format .
    uv run ruff check . --fix

# Build the wheel and source distribution.
build:
    uv build --no-sources
