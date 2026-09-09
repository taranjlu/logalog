# malideiter

`malideiter` is the temporary name for a Python logging library.
It uses Loguru, Rich, and Beartype.

## Status

The first core layer provides typed logging methods and Rich output on stderr.
Delivery is synchronous. Queue support comes next.
No package release or public repository exists as part of this setup.

## Usage

```python
from malideiter import LOG

LOG.info("Task {}: {state}", 17, state="complete")
LOG.debug("Worker started")

try:
    raise ValueError("Invalid task")
except ValueError:
    LOG.exception("Task failed")
```

Use `trace`, `debug`, `info`, `success`, `warning`, `error`, or `critical` for messages.
Use `exception` for an error with the current traceback.
Use `LOG.log("WARNING", "Message")` to select a severity by name.

Messages must be strings. Arguments use Loguru format syntax.
Named arguments also remain in the Loguru record.
Rich treats message text as literal text, not markup.
Tracebacks exclude local variable values, but exception messages and source lines can still contain sensitive data.

Import produces no output and starts no worker thread.
The first valid call creates one reusable stderr console.
The library does not create a stdout console or change application logging handlers.
Keep stdout available for application data, command results, and machine-readable output.

All severities are visible in this layer, including debug and trace.
Live environment controls, file output, configuration loading, and advanced Rich content come in later layers.
Do not use Python `-O` or `-OO`. Beartype disables runtime checks in those modes.

## Plan

Use the [build checklist](docs/checklist.md) for the next work chunks.
Keep the [development plan](docs/plan.md) as reference material.

## Structure

- `src/malideiter/`: package source and type marker.
- `tests/`: tests for package behavior.
- `pyproject.toml`: package metadata and tool settings.
- `uv.lock`: exact development dependency versions.
- `justfile`: development commands.
- `mise.toml`: development tool versions.

## Development

Use Python 3.11 through 3.14 and `uv`.
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
Use `just test-matrix` to test each supported Python version in a separate environment.
Tests cover output, caller information, exceptions, runtime type checks, threads, import safety, and application handler isolation.

The backend adapter uses private Loguru constructors to create an independent logger.
Copying the shared logger can fail when an application has existing file handlers.
The dependency range limits Loguru to `>=0.7.3,<0.8`.
Test the adapter before changing that range.

## Scope

Add one working layer at a time.
Choose the license before public distribution.
