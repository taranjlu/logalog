# malideiter

`malideiter` is the temporary name for a Python logging library.
It uses Loguru, Rich, and Beartype.

## Status

The seven implemented layers provide typed logging, Rich output, and live environment controls.
They also provide files, configuration loading, sections, decorators, and command display.
Delivery uses Loguru's queue by default. A synchronous override is available.
No package release or public repository exists as part of this setup.

## Usage

```python
from malideiter import LOG

LOG.info("Task {}: {state}", 17, state="complete")
LOG.debug("Worker started")
LOG.verbose("Worker is still active")

try:
    raise ValueError("Invalid task")
except ValueError:
    LOG.exception("Task failed")
```

The same methods accept Rich renderables. The logger supports tables, syntax blocks,
text, and multiline groups. It renders each accepted object before queue submission.
This action gives the event a stable snapshot and supports mutable or non-pickleable
renderables. Do not pass format arguments with Rich objects. Add fields by keyword.

```python
from rich.syntax import Syntax
from rich.table import Table

table = Table(title="Tasks")
table.add_column("State", style="green")
table.add_row("complete")
LOG.info(table, task_id=17)
LOG.info(Syntax("value = '{literal}'", "python"))
```

Rich objects appear below their log header and use the full console width.
The producer reserves room for section indentation before it renders an object.
Ordinary strings remain beside their log metadata. Text files get
plain readable output. JSON records contain the same plain message and user fields.
They do not contain ANSI sequences or private Rich objects. Suppressed events do not
render their content.

Call `LOG.configure(synchronous=True)` before the first log call to write in the
calling thread. Use `LOG.configure(prefix="MY_APP")` to replace the default
`MALIDEITER` environment prefix. Call `LOG.flush()` to wait for queued records. Call
`LOG.shutdown()` after workers stop to flush records and close the owner handler.

Configure files before the first log call. Each destination uses Loguru's native file
management. The default rotates at 10 MB and retains five archives.

```python
from malideiter import FileDestination, LOG

LOG.configure(
    files=(
        FileDestination("logs/app.log", compression="gz"),
        FileDestination("logs/app.jsonl", kind="json", delay=True),
    )
)
```

Set `rotation=None` or `retention=None` to disable that option. The API also accepts
Loguru size and time strings, archive counts or ages, `watch`, append or write mode,
encoding, and buffering. Each path must be unique in one configuration.
Do not use overlapping filename patterns or share files between independent owners.
Use `mode="w"` only when you intend to discard an existing file.

Load an explicit ordered list of TOML, JSON, or YAML files before initialization.
For `pyproject.toml`, the loader reads only `[tool.malideiter]`. Later files
override earlier scalar and list values. Mappings merge recursively.

```python
from malideiter import LOG, load_configuration

settings = load_configuration("pyproject.toml", "logging.yaml")
LOG.configure(configuration=settings)
```

The root keys are `synchronous`, `prefix`, `verbose`, `debug`, `silent`,
`modules`, and `files`. A module entry accepts only the three control keys.
Each file entry accepts the `FileDestination` fields. Relative destination paths
use the directory of the source that supplies the final `files` list.
The loader fixes these paths before the working directory can change.
For `pyproject.toml`, quote dotted module names: `[tool.malideiter.modules."myapp.worker"]`.

The loader does not search for files or read command-line options. It does not load
environment variables, `.env` files, interpolation, or executable settings. YAML uses
a private subclass of PyYAML's safe loader. Configurator merges the parsed mappings.

The loader rejects XML and YAML merge keys. Unknown keys, duplicate keys, and incorrect
types raise `ConfigurationError`. Each source must pass validation, even if a later file replaces its settings.

Null module controls restore inheritance. Null rotation, retention, and compression
disable those options. Other nulls are invalid. An empty `files` list replaces earlier destinations.

Stored controls supply defaults. Live environment values still take priority at
the same scope on every call. Explicit `LOG.configure()` delivery arguments take
priority over loaded delivery settings.

Text files keep ordinary messages unwrapped. Rich snapshots retain their rendered layout.
JSON Lines uses Loguru's native `text`
and `record` fields. Both formats retain exception details without local variable values.
Initial setup failures close earlier sinks, but can leave empty files.

Shutdown is final. Later log calls raise `RuntimeError`.
The shared logger also flushes at normal interpreter exit, including an unhandled exception.

For multiprocessing, set the process start method first. Then call
`LOG.initialize()` in the owner before processes start. Serialization also initializes an unused logger.
Pass `LOG` to each worker
and call `initialize_worker(owner)` before the worker logs. Each worker must call
`LOG.flush()` before it exits. Forced process termination can lose queued records.

Keep the owner alive until all workers finish.
For `fork`, start workers before application threads. Loguru manages its own queue-thread locks across fork.
The Linux tests cover `fork`, `spawn`, and `forkserver`.

Use `trace`, `debug`, `verbose`, `info`, `success`, `warning`, `error`, or `critical`
for messages.
Use `exception` for an error with the current traceback.
Use `LOG.log("WARNING", "Message")` to select a severity by name.

Use sections to group nested work. Each event gets `section_depth`, `section`, and
`section_parent` fields before queue submission. Each logger keeps separate section
state for threads and asynchronous tasks. Set `elapsed=True` to show monotonic elapsed
time on completion or failure.

Create a fresh section object for each concurrent operation. Sequential reuse is
supported, but simultaneous reuse is not. Child tasks inherit the creation-time
context. Spawned workers start without section context.
The section metadata keys replace user fields with the same names.

```python
with LOG.section("Import", elapsed=True):
    LOG.info("Read source")


@LOG(elapsed=True)
def update() -> None:
    LOG.info("Update data")
```

`@LOG` supports ordinary synchronous and asynchronous functions. It preserves returns,
exceptions, and function metadata. It does not support generators or asynchronous
generators. It does not log function arguments.

Async lifecycle messages use the decorated function's definition location and module
controls, including when the event loop schedules the function. Body messages keep
their own caller locations. Synchronous lifecycle messages keep the call site.

Use `LOG.command(["tool", "--token", token], cwd="work", redact_indices=(2,))` to
display a command and its planned working directory. The helper uses the POSIX or
Windows platform quoting convention. The display is not universal shell syntax. It
never executes the command or changes directories.

Redaction uses only the argument indices and exact values that you give it.
Use `redact_values` to hide an exact `cwd` value. An invalid redaction index stops
the call before logging. The `command` and `cwd` record fields contain the display values.

Use strings for command arguments and redaction values. Runtime type errors can
include argument representations. Quoting does not escape embedded newlines.
Do not treat command display as a sanitizer for untrusted terminal text.

String arguments use Loguru format syntax. Strings stay literal when no arguments are
present. Named arguments also remain in the Loguru record.

Queued fields must support Python pickle serialization. Serialization failures raise in the calling thread.
Queued sink failures use Loguru error output and do not raise in the calling thread.
Flush waits for delivery attempts. It does not guarantee that a failed destination received the records.

Rich treats message text as literal text, not markup.
Queued tracebacks use plain traceback text inside the Rich message. Synchronous tracebacks retain Rich formatting.
Tracebacks exclude local variable values, but exception messages and source lines can still contain sensitive data.

Import produces no output and starts no worker thread.
The first emitted record creates one reusable stderr console.
The library does not create a stdout console or change application logging handlers.
Keep stdout available for application data, command results, and machine-readable output.

Debug and verbose output are off by default. Set `MALIDEITER_DEBUG=1` or
`MALIDEITER_VERBOSE=1` to enable each category independently. Set
`MALIDEITER_SILENT=1` to suppress all output. Each call reads current values from
`os.environ`. Changes apply in the calling process, before queue submission.

Accepted records keep their decision while queued. A later parent-process change does not update an existing worker.

Import `environment_names` from `malideiter` to get all global and exact-module names.
For example, call `environment_names("myapp.worker", prefix="MY_APP")`. Use the same prefix as `LOG`.

Module settings inherit from parents. A child value overrides inherited debug or
verbose values. A child cannot cancel inherited silence. Module name parts use
uppercase UTF-8 hex, which keeps case and underscores distinct.

Accepted Boolean values are `1`, `true`, `yes`, and `on`, or `0`, `false`, `no`,
and `off`. Case and outer whitespace do not matter. An invalid applicable value
raises `ConfigurationError` before queue submission.

Do not use Python `-O` or `-OO`. Beartype disables runtime checks in those modes.

## Plan

Use the [build checklist](docs/checklist.md) for the next work chunks.
Keep the [development plan](docs/plan.md) as reference material.

## Runnable example

From the repository root, run:

```bash
uv run python examples/workflow.py
```

The example merges TOML and JSON settings. It runs concurrent tasks, renders a
table, changes a live debug control, and displays a redacted command. It also
logs and handles a deliberate exception. Exit code 0 shows completion.

Output goes to stderr and `examples/logs/workflow.log` and `examples/logs/workflow.jsonl`.
Repeated runs append records. Rotation limits each active file to about 10 MB
and retains two archives. The displayed command does not run.
The example restores its process-local debug setting and closes the logger.

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

Full test runs fail below 100% line and branch coverage of `malideiter`.
Coverage includes subprocess execution.
Use `just coverage` to write an HTML report to `htmlcov/index.html`.
Use `just test-images` for the OpenImageIO visual regression checks.
They cover levels, wrapping, indentation, tables, styles, code, and commands
at multiple widths in both delivery modes.
See [image test guidance](tests/visual/README.md) for fonts and reference updates.

For focused tests, use `uv run pytest --no-cov <test-path>`.
Run the full suite before you finish a change. Do not add exclusions to reach the coverage target.

The backend adapter uses private Loguru constructors to create an independent logger.
Copying the shared logger can fail when an application has existing file handlers.
The dependency range limits Loguru to `>=0.7.3,<0.8`.
Test the adapter before changing that range.

## Scope

Add one working layer at a time.
Choose the license before public distribution.
