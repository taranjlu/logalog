# logalog

Logalog is a Python logging library built with Loguru and Rich.
The distribution and import package use the name `logalog`.
Check name availability again before public release.

## Status

The seven implemented layers provide typed logging, Rich output, and live environment controls.
They also provide files, configuration loading, sections, decorators, and command display.
Delivery is automatic by default: synchronous in one process, queued for worker processes.
No package release or public repository exists as part of this setup.

## Usage

```python
from logalog import LOG

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

Select the stderr output mode before the first log call:

- `rich`, the default, is for a terminal. It does not show attached fields.
- `plain` writes one readable line per record, with attached fields as `key=value` at the end.
  Values with spaces, quotes, or `=` use JSON quoting.
- `json` writes one JSON object per line. The keys are `time`, `level`, `name`, `function`,
  `line`, `process`, `thread`, `message`, `extra`, and `exception`.

```python
LOG.configure(stderr="json")
LOG.info("request finished", request_id=request_id, status=201, elapsed_ms=12)
```

The `plain` and `json` modes do not load Rich, unless a message is a Rich object.
They include exception tracebacks as text. With these modes, fields that JSON cannot
encode raise `ValueError` before any destination receives the event.
Use the `stderr` key in a configuration file to select the mode.

By default, delivery is automatic. Records write in the calling thread until
`LOG.initialize()` runs. That call creates the owner queue for worker processes.
Call `LOG.configure(synchronous=True)` or `LOG.configure(synchronous=False)` before the
first log call to fix one mode. Queued delivery starts a writer thread and a
`multiprocessing` resource tracker process. Synchronous delivery starts neither.
Use `LOG.configure(prefix="MY_APP")` to replace the default
`LOGALOG` environment prefix. Call `LOG.flush()` to wait for queued records.
Flush does not flush file buffers. Files with `buffering=1`, the default, write each line.
Call `LOG.shutdown()` after workers stop to flush records and close the owner handlers.
Shutdown closes every destination, then raises the first close failure.

Configure files before the first log call. Each destination uses Loguru's native file
management. The default rotates at 10 MB and retains five archives.

```python
from logalog import FileDestination, LOG

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
For `pyproject.toml`, the loader reads only `[tool.logalog]`. Later files
override earlier scalar and list values. Mappings merge recursively.

```python
from logalog import LOG, load_configuration

settings = load_configuration("pyproject.toml", "logging.yaml")
LOG.configure(configuration=settings)
```

The root keys are `synchronous`, `stderr`, `prefix`, `verbose`, `debug`, `silent`,
`modules`, and `files`. An omitted or null `synchronous` selects automatic delivery. A module entry accepts only the three control keys.
Each file entry accepts the `FileDestination` fields. Relative destination paths
use the directory of the source that supplies the final `files` list.
The loader fixes these paths before the working directory can change.
For `pyproject.toml`, quote dotted module names: `[tool.logalog.modules."myapp.worker"]`.

The loader does not search for files or read command-line options. It does not load
environment variables, `.env` files, interpolation, or executable settings. YAML uses
a private subclass of PyYAML's safe loader. A short recursive merge combines the parsed mappings.
YAML support is optional. Install `logalog[yaml]` to load `.yaml` and `.yml` files.
Without the extra, a YAML path raises `ConfigurationError` that names the extra.
YAML Booleans follow YAML 1.2: only `true` and `false`, in lowercase, title case, or uppercase.
Values such as `on` and `yes` stay strings.

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
The shared logger also flushes and closes at normal interpreter exit, including an unhandled exception.
Exit handlers that you register before `import logalog` run after that step. Their records
use synchronous delivery. The owner process appends them to its files.

For multiprocessing, set the process start method first. Then call
`LOG.initialize()` in the owner before processes start and before the first record.
Serialization also initializes an unused logger with queued delivery. A logger that
already writes synchronously cannot serialize and raises `ValueError`.
Pass `LOG` to each worker
and call `initialize_worker(owner)` before the worker logs. Each worker must call
`LOG.flush()` before it exits. Forced process termination can lose queued records.
`initialize_worker` raises `ValueError` unless the owner has an initialized queue.
This check also applies to `fork`, where the worker inherits the owner object.
A worker flush waits for the owner writer. Do not flush after the owner stops.

Keep the owner alive until all workers finish.
For `fork`, start workers before application threads. Loguru manages its own queue-thread locks across fork.
A forked child gets a new logalog lock, so a parent thread that logs during `fork` cannot block it.
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
generators. It does not log function arguments. Put `@LOG` above or below
`@classmethod` or `@staticmethod`.

Async lifecycle messages use the decorated function's definition location and module
controls, including when the event loop schedules the function. Body messages keep
their own caller locations. Synchronous lifecycle messages keep the call site.

Use `LOG.command(["tool", "--token", token], cwd="work", redact_indices=(2,))` to
display a command and its planned working directory. The helper uses the POSIX or
Windows platform quoting convention. The display is not universal shell syntax. It
never executes the command or changes directories.

Redaction uses only the argument indices and exact values that you give it.
Give `redact_values` as a collection, such as a tuple. One string raises `TypeError`.
Use `redact_values` to hide an exact `cwd` value. An invalid redaction index stops
the call before logging. The `command` and `cwd` record fields contain the display values.

Use strings for command arguments and redaction values. Other types raise `TypeError`
without the argument values. Quoting does not escape embedded newlines.
Do not treat command display as a sanitizer for untrusted terminal text.

String arguments use Loguru format syntax. Strings stay literal when no arguments are
present. Named arguments also remain in the Loguru record. If the text cannot format with
the arguments, for example because it contains braces, the call logs the literal text
with the fields. Message content never makes a log call raise.

Do not build a template from untrusted text, such as an f-string with request data,
when you also pass fields. Format syntax such as `{request_id.__class__}` can read
attributes of a field value. Pass untrusted data as a field instead.

Queued fields must support Python pickle serialization. Serialization failures raise in the calling thread.
With a JSON destination, fields that JSON cannot encode, such as circular data, raise `ValueError`.
In both cases, no destination receives the event.
Queued sink failures use Loguru error output and do not raise in the calling thread.
Flush waits for delivery attempts. It does not guarantee that a failed destination received the records.

The logger lock covers only call acceptance and backend setup. Formatting and Rich rendering
run in parallel in each calling thread. Loguru writes each record under its own handler lock.
A blocked stderr or a full queue pipe can therefore block calling threads, including an
asynchronous event loop thread. Flush and shutdown have no timeout.
The console shows the event time and the thread that made the call, also for queued records.

Rich treats message text as literal text, not markup.
Queued tracebacks use plain traceback text inside the Rich message. Synchronous tracebacks retain Rich formatting.
Tracebacks exclude local variable values, but exception messages and source lines can still contain sensitive data.

Import produces no output and starts no worker thread. It registers one exit handler for the shared logger.
Import does not load Loguru, Rich, or the TOML and YAML parsers. The first emitted record
loads Loguru and the output modules. A suppressed record loads nothing.
Loguru adds its default handler to its own shared `logger` when it loads.
Logalog does not use or change that shared logger.
The first emitted record creates one reusable stderr console.
The library does not create a stdout console. It changes application logging handlers
only under the standard logging takeover policy below.
Keep stdout available for application data, command results, and machine-readable output.

Debug and verbose output are off by default. Set `LOGALOG_DEBUG=1` or
`LOGALOG_VERBOSE=1` to enable each category independently. The debug control also enables trace output. Set
`LOGALOG_SILENT=1` to suppress all output. Each call reads current values from
`os.environ`. Changes apply in the calling process, before queue submission.

Accepted records keep their decision while queued. A later parent-process change does not update an existing worker.

Import `environment_names` from `logalog` to get all global and exact-module names.
For example, call `environment_names("myapp.worker", prefix="MY_APP")`. Use the same prefix as `LOG`.

Module settings inherit from parents. A child value overrides inherited debug or
verbose values. A child cannot cancel inherited silence. Module name parts use
uppercase UTF-8 hex, which keeps case and underscores distinct.

Accepted Boolean values are `1`, `true`, `yes`, and `on`, or `0`, `false`, `no`,
and `off`. Case and outer whitespace do not matter. Each call reads only the controls
that can suppress it: silence, and also verbose or debug for those levels. It stops at
the first control that suppresses it. An invalid value that a call reads raises
`ConfigurationError` before queue submission.

The library has typed interfaces for Ty and other static type checkers. It does not
check every argument at run time. Explicit checks protect redaction inputs, file
destinations, configuration controls, prefixes, and module names. These checks also work with `-O`.

## Standard logging takeover

The takeover is off by default. It is an explicit ownership policy for the root
handlers of the standard `logging` module. Enable it only in the application that owns
the process, never in a library.

```python
LOG.configure(stderr="json", standard_logging=True)
```

When you enable it, `LOG.configure()` does these steps at once:

- It records the root handlers and the root level.
- It removes those handlers and adds one logalog handler.
- It sets the root level from the controls at that moment. The level is `NOTSET` when
  any debug control is on, 15 when only a verbose control is on, and `INFO` otherwise.
  Global, module, stored, and environment controls count. The check is conservative.

Records below the root level stop in the standard logger at almost no cost.
A library `debug` call costs about 0.1 µs, against 5.4 µs with a `NOTSET` root.
The live controls still decide each record that passes the root level.
Set a debug or verbose control for standard-library loggers before the takeover.
A debug control that you turn on later does not show standard `debug` records.
Configure again with `standard_logging=False` and then `True` to apply new controls.

Records that reach the root logger then use logalog delivery, stderr mode, files,
sections, and live controls. The logger name is the module for the controls and for
the `name` field. The record keeps its own function, file, and line.
Levels map down to the nearest logalog level: `DEBUG` (10), `VERBOSE` (15),
`INFO` (20), `SUCCESS` (25), `WARNING` (30), `ERROR` (40), and `CRITICAL` (50).
Levels below 10 map to `TRACE`. Exception information stays with the record.
Standard `extra` attributes do not become logalog fields.

`LOG.shutdown()`, also at interpreter exit, removes the logalog handler first.
It then adds the recorded handlers back and restores the recorded root level.
Handlers that the application added after the takeover stay in place.
`LOG.configure(standard_logging=False)` before the first record also restores the root.
When the option is off, logalog does not read or change any standard logging object.

The takeover applies only to records that reach the root logger:

- A logger with its own handlers and `propagate=False` keeps its own output.
  For Uvicorn, pass `log_config=None` to `uvicorn.run()` so its loggers propagate.
- A logger with its own level still filters records before the root.
- A logger with level `NOTSET` uses the root level as its effective level.
- Silence a content-bearing logger with a module control, for example
  `modules: {"uvicorn.access": {silent: true}}` in a configuration file.
- If logalog rejects a record, for example for an invalid control value, the standard
  logging error handler reports it on stderr. That report includes the message.

The takeover applies to the process that calls `LOG.configure()`. Worker processes
do not take over their own root logger.

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

- `src/logalog/`: package source and type marker.
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
`just check` runs Ruff, Ty, Complexipy, Deptry, Vulture, Bandit, and pip-audit.
Use `just lint` for local static checks. `just security` needs network access
for its audit of locked runtime dependencies. Development tools are not runtime dependencies.

Complexipy compares functions against `complexipy-snapshot.json` and a threshold of 15.
The baseline records existing complexity in `command` and `_deliver`.
Review those functions before replacing the baseline with `uv run complexipy --snapshot-create`.
Do not update it only to make a check pass. Vulture checks source and tests at 90% confidence.
Bandit reports findings with at least medium severity and medium confidence.

Pytest Randomly changes test order and reports its seed. Use `just test-random 42`
to repeat a seed. Hypothesis checks module-name encoding across Unicode inputs.
Pytest Asyncio runs coroutine tests in strict mode with function-scoped event loops.

Pytest Sugar supplies interactive progress. Use `just test-spec` for specification
output. That command disables Sugar to prevent conflicting output formats.

Use `just matrix` to run the Python 3.11–3.14 tests through Nox and uv.
The four Python sessions run concurrently. Tests within each session remain sequential.
Each session keeps coverage data, the pytest cache, and Hypothesis data in its own
`.nox/tests-3-XX/test-artifacts/` directory and independently enforces 100% coverage.
Nox currently labels parallel execution experimental.

Use `uv run nox --parallel 1` for sequential sessions.
`just test-matrix` remains an alias. Nox reuses isolated environments, installs
from the frozen lockfile, and fails if a required interpreter is missing.
Use `uv run nox -s tests-3.12 -- --randomly-seed=42` to select a session and pass pytest arguments.
Tests cover output, caller information, exceptions, explicit input checks, threads, import safety, and application handler isolation.

Full test runs fail below 100% line and branch coverage of `logalog`.
Coverage includes subprocess execution.
Use `just coverage` to write an HTML report to `htmlcov/index.html`.
Use `just test-images` for the OpenImageIO visual regression checks.
They cover levels, wrapping, indentation, tables, styles, code, and commands
at multiple widths. Two representative cases also check queued delivery.
See [image test guidance](tests/visual/README.md) for fonts and reference updates.

For focused tests, use `uv run pytest --no-cov <test-path>`.
Run the full suite before you finish a change. Do not add exclusions to reach the coverage target.

Each accepted call creates one Loguru event. Native file sinks retain its original
message, exception, timestamp, and user fields. The console adapter changes only
a local copy for presentation. Prepared console data stays outside JSON record fields.

The backend adapter uses private Loguru constructors to create an independent logger.
It also reuses Loguru's private `StandardSink` adapter for Rich output.
Copying the shared logger can fail when an application has existing file handlers.
The dependency range limits Loguru to `>=0.7.3,<0.8`.
Test the adapter before changing that range.

## Scope

Add one working layer at a time.
Choose the license before public distribution.
