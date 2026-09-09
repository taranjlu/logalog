# malideiter

`malideiter` is the temporary name for a Python logging library.
The planned library uses Loguru, Rich, and Beartype.

## Status

This repository contains the package skeleton and development tools.
The package does not yet provide the logging API or `LOG`.
Runtime dependencies will enter the project with the code that uses them.
No package release or public repository exists as part of this setup.

## Structure

- `src/malideiter/`: package source and type marker.
- `tests/`: tests for package behavior.
- `pyproject.toml`: package metadata and tool settings.
- `uv.lock`: exact development dependency versions.
- `justfile`: development commands.
- `mise.toml`: development tool versions.

## Development

Use Python 3.11 or later and `uv`.
The development tool versions are in `mise.toml`.

```bash
uv sync
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest
uv build --no-sources
```

With `just` available, use `just check`, `just test`, and `just build`.
The initial test checks that package import produces no output and starts no worker thread.
It does not test logging behavior.

## Scope

Keep the first implementation small.
Add a supported Python test matrix when runtime code enters the project.
Choose the license before public distribution.
