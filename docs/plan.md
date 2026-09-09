# malideiter development plan

Status: Draft for review. This change adds no logging implementation.
Research date: 2026-09-09.

## Goal

Build a Python logging library with one import, readable Rich output, and dependable queued output across threads and processes.
Use `malideiter` as the temporary repository, distribution, and import name.

The intended entry point is:

```python
from malideiter import LOG

LOG.info("Task complete")
LOG.debug("Diagnostic detail")
LOG.verbose("Additional progress detail")
```

These examples describe the target API. They do not work in the skeleton.
Utility names and configuration details below remain proposals.

## Requirements and proposals

The requested design includes:

- Loguru for logging configuration and delivery.
- Rich for human-readable messages, with separate structured output.
- Reusable stdout and stderr consoles when both output streams are in use.
- Human-readable and structured log files, with rotation and other applicable Loguru file features.
- Beartype for runtime type checking within the library.
- Queued output by default and a synchronous override.
- Independent verbose and debug controls, plus a separate silence control.
- A global environment variable and an automatically generated per-module variable for each of the three controls.
- Live environment checks on every log call, without restart, polling delay, or a reload command.
- Configuration from `pyproject.toml`, TOML, YAML, JSON, and XML, with defined merge rules.
- One imported `LOG` object for normal use.
- Utilities for nested sections, function logs, elapsed time, and subprocess command display.

This plan proposes defaults where the request leaves behavior open.
The main proposals concern startup, silence, configuration priority, module names, and output formats.
Approve those defaults before implementation. A proposal is not an accepted decision.

## Starting point

The skeleton uses the reference project's `src/` layout, `uv`, Ruff, Ty, pytest, and `just` commands that run the development tools.
It includes a type marker and a test for silent import without new worker threads.
It does not include runtime dependencies, a configuration framework, or release automation.
Python 3.11 is the initial minimum. Verify Python 3.11 through 3.14 before claiming that full support range.

## Core design

### Public API and existing application logs

Export one stable `LOG` object. Do not make callers create a logger for each module.
Preserve the caller's full module name, source location, and attached data when a helper forwards a log call.
Provide typed methods for normal severity levels, such as info, warning, and error.
Treat verbose messages as a separate category.
Keep the supported API explicit rather than promise every Loguru method.

Proposed default: initialize logging on the first log call. Send Rich output to standard error (`stderr`), not application standard output (`stdout`).
Keep import silent. Do not start a queue worker or search for configuration files during import.

Allow explicit configuration before first use, including an application-specific environment prefix.
Default the prefix to `MALIDEITER`. Do not infer it from whichever module imports first.

Loguru shares one logger, and its documentation warns about handler changes from libraries.[2]
A handler connects a logger to an output destination.
Test how the library can manage its own handlers without changing the application's handlers.
Do not remove application handlers, duplicate output, or capture unrelated logs by default.
Defer the capture of standard-library logs. Add that integration only through an explicit option.

### Queued and synchronous output

Use Loguru's `enqueue=True` as the default delivery model.
Calls such as `LOG.info()` submit records to a queue. A background worker writes those records to the output destination.
Callers do not use `await LOG.info()`.

A sink is an output destination, such as a file or terminal.
Loguru distinguishes queued handlers from coroutine sinks and provides `complete()` for shutdown.[1]
Support ordinary logging without an asyncio event loop.
Provide a configuration override for direct, synchronous output with `enqueue=False`.

Define which process creates and manages the queue. Test child-process setup and shutdown for each supported process start method.
Include `spawn`, `forkserver`, and `fork` where the platform provides them.
An independently started process needs an explicit connection or initialization path.
Do not claim that an import alone creates a shared queue across unrelated processes.

Define how to finish queued output before shutdown, close handlers, and change configuration.
Define behavior when an output destination fails or cannot keep pace with incoming messages.
Measure log-call delays under load. Queued output does not guarantee that every call returns immediately.
Document normal-shutdown guarantees and possible loss after forced termination.
Do not promise one exact event order across all threads and processes.

### Reusable stdout and stderr consoles

Rich supports reusable console instances. It does not need two consoles for every application.[11]
`Console()` uses stdout by default. `Console(stderr=True)` selects stderr unless an explicit `file` overrides it.[14]
Use one reusable console for each output stream that the library enables. Do not create a console for every message.

Propose `STDOUT_CONSOLE` and `STDERR_CONSOLE` as names for shared console access.
Keep `LOG` as the normal logging API. Send diagnostics to stderr by default.
Reserve stdout for intentional application output or an explicit logging destination.
Do not send the same record to both consoles unless configuration requests it.
Keep protocol data and structured stdout output separate from Rich output.

Create the consoles when needed and reuse them within the process that owns the output.
Do not treat console instances as shared objects across independent processes.
Allow an application to supply its own consoles. Test redirected streams and terminal capabilities separately for stdout and stderr.

Direct console calls bypass `LOG`, its live environment controls, and file destinations. Document this distinction.
Use separate rendering contexts only when a file destination needs different formatting. Two consoles do not limit the number of log destinations.

### Human-readable and structured output

Use Rich for every human-readable output path, including plain terminal output without color.
Support wrapped text, multiline messages, tables, code blocks, and exceptions.
Rich's `Console` handles renderable objects and terminal properties.[11]
`RichHandler` provides text logging and traceback support.[3]
Test whether custom Rich objects can pass through the queue.

Keep event data separate from its terminal appearance.
Compare two queue payloads: Rich objects and a data description from which the output worker builds Rich objects.
Serialization converts a payload into a form that can pass between processes. Test which payloads support this conversion.

Define when the logger copies message data. Test objects that change after the log call.
Render at the output destination where practical so wrapping uses its width.

Give each event stable fields for severity, message category, text, module, context, and exception data.
Propose separate output writers for Rich, JSON Lines, and optional MessagePack.
JSON Lines stores one JSON record per line.
Keep structured output free of ANSI sequences and terminal markup.

`msgspec` is an encoder and validation library, not a file format. It supports JSON and MessagePack.[9]
Assess it after the event schema exists. Do not add a second schema framework without a clear need.

Treat ordinary strings as literal text. Accept markup only through an explicit option. Escape untrusted content.
Do not include local variables in exception reports or capture function arguments by default.
Remove or mask sensitive fields before they enter the queue or any output destination.

### File output and rotation

Support human-readable text files and structured JSON Lines files, independently or alongside terminal output.
Make file destinations explicit. Do not create log files merely because an application imports the package.
Render human-readable content through Rich without terminal control sequences. Configure file width separately from terminal width.
Send structured records directly to the encoder without Rich rendering.

Use Loguru's native file-path sinks for file management.
Loguru supplies rotation, retention, compression, delayed file creation, file watching, and file-opening settings for these sinks.[1]
Passing an open file or a callable sink does not automatically retain those file-path features.[1]
Test the Rich rendering path with native file management before selecting the integration.
Do not build a second rotation system or rely on Loguru's private classes.

Expose applicable file options through typed configuration:

- Rotation by size or time, with trusted programmatic callbacks where needed.
- Retention by archive count or age.
- Archive compression, such as gzip.
- Delayed creation and optional reopening after external file replacement.
- File paths, filename time fields, append mode, encoding, and buffering.

Define finite rotation and retention defaults for the file preset before enabling it.
Allow explicit overrides, including a deliberate no-rotation option.
Use one writer and rotation owner for each shared file across processes.
Do not let independent workers rotate the same path.
Define behavior for permission failures, full disks, compression failures, and shutdown with pending records.
Never log from a rotation, retention, or compression callback through the same logging path.

Loguru's `serialize=True` produces JSON, not MessagePack.[1]
Start structured file support with JSON Lines. Keep MessagePack optional.
Before adding binary files, prove that their encoder and writer preserve the same rotation and shutdown guarantees.
Do not assume that a custom binary sink inherits Loguru's native file management.

A disposable test with Rich 15.0.0 and Loguru 0.7.3 confirmed separate console routing and native queued file output.
Text and JSON Lines tests passed size rotation, count retention, gzip compression, and delayed creation.
Retained JSON records decoded successfully. This test did not verify the complete Rich-to-Loguru integration or multiprocessing.

### Independent environment controls

Provide both global and per-module versions of `VERBOSE`, `DEBUG`, and `SILENT`.
Generate each module's variable names automatically from its full name. Do not make callers register these names.
The global variables apply across modules. Module variables change behavior for the selected module under the inheritance rules below.

Example for the prefix `MALIDEITER` and module `myapp.worker`:

| Control | Global variable | Automatically generated module variable |
| --- | --- | --- |
| Verbose | `MALIDEITER_VERBOSE` | `MALIDEITER_MODULE__MYAPP__WORKER_VERBOSE` |
| Debug | `MALIDEITER_DEBUG` | `MALIDEITER_MODULE__MYAPP__WORKER_DEBUG` |
| Silent | `MALIDEITER_SILENT` | `MALIDEITER_MODULE__MYAPP__WORKER_SILENT` |

Both scopes are requirements for every control. The exact module-name encoding remains a proposal.
Substitute the configured prefix for `MALIDEITER`.

Use independent on/off controls, not one minimum severity level.
Loguru supports callable filters for each sink.[1]
Set each sink to accept the relevant levels, then use the filter to select verbose and debug messages independently.

Proposed behavior:

| Verbose | Debug | Additional output |
| --- | --- | --- |
| Off | Off | None |
| On | Off | Verbose only |
| Off | On | Debug only |
| On | On | Verbose and debug |

Normal messages remain available in each row unless silence applies.
Propose that global `SILENT=true` suppress all library-owned output, including errors and structured destinations.
Apply module silence only to that module and its children.
Confirm these silence rules before implementation.

Use the same module-name encoding for all three controls.
Specify encoding and collision handling before adopting the proposed names above.
Test underscores, case differences, nested modules, and `__main__`.

Provide a public helper that accepts a module name and returns every exact environment variable name.
Also expose effective settings and their sources without revealing secrets.
Return names without module import or earlier log output.

Proposed module rule: start with global settings, then apply parent-module settings, then exact-module settings.
For example, `myapp.worker` inherits settings from `myapp` unless it has an explicit override.
An unset value inherits. Explicit `false` can disable inherited verbose or debug output.
A child module cannot cancel silence from a parent module.
Define accepted Boolean strings and reject invalid values with a named configuration error.

### Live environment changes

Each log call reads the applicable controls directly from the current process's `os.environ`.
A change takes effect on the next call, including calls that an earlier value would suppress.
Check both scopes on every call: global controls and applicable parent-module and exact-module controls.
Apply this live-check rule to verbose, debug, and silence controls alike.
Detect additions, value changes, and deletions without restart or explicit configuration reload.
Do not cache environment values or resolved on/off decisions between calls.

Cache only stable lookup information, such as generated variable names and module-parent paths.
Use direct key lookups and small Boolean conversions. Do not scan or copy the whole environment.
Keep file loading and configuration-library reconstruction outside the log-call path.
Skip library-controlled formatting, Rich rendering, and queue serialization when the controls suppress a message.
This cannot avoid argument evaluation that the caller completes before the log call.

For these three controls, live environment values override file and API values at the same module scope.
When a variable disappears, use the remaining configuration and module inheritance rules.
Other settings retain the source order below.

Evaluate the controls in the calling process in both modes. In queued mode, evaluate them before queue submission.
Proposed queue rule: accepted records retain that decision while they wait for output.
Do not recheck them against the output worker's environment.
Under this proposal, silence affects new calls but does not cancel records already in the queue.
Confirm this queue rule before implementation.

Support live updates through `os.environ`. Direct `os.putenv()` calls do not update that Python mapping.[13]

Environment values belong to each process. A later shell or parent-process change does not update an existing worker's environment.
Update each logging process separately. Cross-process control would need a separate communication mechanism.
Do not promise one atomic update when another thread changes several variables during a log call.

Measure enabled and suppressed calls, short and deep module paths, and repeated value changes.
Include module lookup, type checks, environment reads, and Boolean conversion in the measurements.
Compare against a fixed-setting baseline. Select optimizations from measured results without weakening live checks.

## Configuration research

Support `[tool.malideiter]` in `pyproject.toml`, separate TOML, YAML, JSON, and XML files.
Load an explicit ordered list of files and merge their settings into one validated configuration.
Treat file storage as user-authored configuration initially. Automatic rewriting and comment preservation remain outside the first version.

### Candidate libraries

| Candidate | Documented support | Main assessment |
| --- | --- | --- |
| Dynaconf | TOML, YAML, JSON, environment variables, custom loaders, and configurable merges.[4][5][6] | Test first for layered files. XML needs an adapter. Check nested merge limits and disable unwanted loader features. |
| Pydantic Settings | Sources for `pyproject.toml`, TOML, YAML, and JSON, with configurable source order.[7] | Compare typed validation and error quality. XML needs a custom source. Assess added dependency cost beside Beartype. |
| OmegaConf | YAML and dictionary input, structured configuration, and merge operations.[10] | Keep as a comparison. TOML and XML need adapters. Its interpolation features exceed the current requirement. |

The project has no configuration dependency yet.
Start with a small Dynaconf and Pydantic Settings comparison using the same fixtures.
The reviewed source lists do not establish native XML support for either candidate.[4][7]
Dynaconf documents merge caveats.[5]
Pydantic Settings documents shallow file merges unless the caller enables deep merge.[7]
Verify these behaviors against pinned releases, not only the current documentation.

Choose the library with the least custom code that meets the required behavior.
If neither fits, compare a small loader layer over existing parsers and a merge library.
Do not build a general configuration framework.

### Proposed configuration rules

Load settings in this order. Later sources override earlier values at the same module scope:

1. Built-in defaults.
2. The selected `pyproject.toml` section.
3. Explicit configuration files, in caller order.
4. Environment variables.
5. Explicit API settings.

For `VERBOSE`, `DEBUG`, and `SILENT`, use the live environment override rule above instead of this source order.
Then resolve module inheritance and apply the silence rules.
A module-specific value takes priority over a global value, except where a silence rule prevents output.
Confirm this interaction between source priority and module scope before implementation.

Other rules:
- Merge mappings recursively. Replace lists and scalar values by default.
- Define deletion, null values, duplicate keys, and type conflicts explicitly.
- Report the source file, setting path, and effective origin for errors.
- Do not search parent directories or load `.env` files without a defined opt-in policy.
- Use safe YAML parsing. Reject XML external entities and document type declarations.
- Define one XML schema for lists, mappings, and scalar types. Do not guess from arbitrary XML shapes.
- Disable executable configuration, arbitrary imports, and template evaluation.

## Runtime type checking

Use Beartype to check typed functions and methods within this library. Do not apply its checks to unrelated application packages.
Prefer explicit decorators where they keep the boundary clear.
If a package import hook is necessary, restrict its scope and make decoration failures fatal.

Beartype's documentation describes sampled container checks by default and marks `BeartypeStrategy.On` as unimplemented.[12]
A sampled check inspects selected container items, not every item.
Do not describe it as a complete check of all data.
Verify the pinned release with wrong arguments, return values, and nested container items.
Use explicit validation where every configuration or event item must pass.

Keep annotations specific. Avoid broad `Any` types that remove useful enforcement.
Check decorator compatibility, coroutine behavior, Rich protocols, and queue serialization.
Measure runtime cost without disabling the required checks.

## Utility functions

Add utilities after the event format, output behavior, and shutdown rules are stable:

- A section context manager with recursive indentation and optional elapsed time.
- Function decorators that record entry, completion, failure, and optional elapsed time.
- A subprocess command display helper that accepts an argument sequence and never executes it.

Keep a separate section context for each concurrent task. Use `contextvars` rather than one shared indentation counter.
Capture section depth, section identity, and parent identity in each event before queue submission.
Keep structured depth fields as well as visual indentation.
Restore context after exceptions and cancellation. Define context transfer to child tasks, threads, and processes.

Measure elapsed time with a monotonic performance clock. This clock avoids changes to the system date and time.
Preserve function metadata, return values, exceptions, and coroutine behavior.
Do not consume generators or log function arguments automatically.
Define generator support separately before claiming it.

For command display, quote and wrap arguments clearly. Show the working directory and mask fields that the caller marks as sensitive.
Specify the display convention for each supported shell or platform.
Do not imply that one quoted command string is portable across shells.

## Execution stages

1. **Test the main design risks.** Compare configuration libraries. Test Rich payloads, native file rotation, process queues, shutdown, and runtime checks.
2. **Approve the design choices.** Select the configuration library, silence rules, module names, type-checking limits, and handler rules.
3. **Build the core.** Add typed `LOG` methods, shared consoles, rotating text files, queued and synchronous modes, filters, and lifecycle controls.
4. **Add configuration.** Implement the selected loader, each specified file format, module overrides, and settings discovery.
5. **Add structured output and utilities.** Implement rotating JSON Lines files and assess MessagePack. Add sections, timers, decorators, and command display.
6. **Verify and document.** Test the supported Python and operating-system matrix, dependency security, built wheels, and examples.

Use small behavior tests throughout. Do not impose test-driven development or a commit after every task.
Keep implementation outside this initial planning change.

## Completion checks

- One import supports ordinary use without extra setup code.
- Each control has a global variable and automatically generated module variables.
- The discovery helper returns the exact verbose, debug, and silence names for any valid module name.
- All verbose and debug combinations work globally and per module.
- Global and module silence each follow the approved rules without changing unrelated modules unexpectedly.
- Adding, changing, or deleting a control in `os.environ` affects the next call without reload.
- Repeated off/on changes work after suppressed calls, across threads, and in queued and synchronous modes.
- Each process reads its own environment. Queued records follow the approved queue rule.
- Measurements include live-check overhead on enabled and suppressed calls.
- Silence, explicit false values, module-name collisions, and setting priority follow the documented rules.
- All required configuration formats produce equivalent settings and merge results.
- Threads and supported process models produce complete, non-duplicated events during controlled shutdown.
- Concurrent sections keep separate context and restore it after failures.
- Rich output wraps at narrow widths. Tables, code blocks, exceptions, and literal brackets remain readable.
- Stdout and stderr consoles reuse their configured streams without duplicate records or protocol contamination.
- Text and JSON Lines files rotate, retain archives, and compress according to configuration.
- File tests cover delayed creation, external replacement, permission errors, full disks, and shutdown.
- Concurrent workers use one rotation owner per shared file. Retained records remain complete and readable.
- JSON Lines and optional MessagePack decode independently and retain context without terminal formatting.
- Invalid arguments fail before the affected operation starts. Invalid return values fail before they reach the caller. Test nested invalid data too.
- Command display never executes a command or reveals fields marked for redaction.
- Formatting, linting, type checks, tests, package builds, and isolated wheel checks pass.
- Documentation passes the planned ASD-STE100 review without a false compliance claim.

## Decisions before implementation

Confirm the silence scope and whether silence cancels records already in the queue.
Keep live environment controls above file and API values at the same module scope.

Approve the module-name encoding and configuration discovery policy.
Select a configuration library after the comparison, including its secure XML path.
Choose how Rich content passes through the queue and how the library manages its Loguru handlers.
Approve shared console access and the default rotation and retention policy for files.
Specify where every data item needs validation. Define the supported Python versions and operating systems.

Choose a license before public distribution. Check name availability before replacing the code name or publishing.

## Sources

[1] https://loguru.readthedocs.io/en/stable/api/logger.html

[2] https://loguru.readthedocs.io/en/stable/resources/recipes.html

[3] https://rich.readthedocs.io/en/stable/logging.html

[4] https://www.dynaconf.com

[5] https://dynaconf.com/merging

[6] https://www.dynaconf.com/advanced

[7] https://docs.pydantic.dev/latest/concepts/pydantic_settings

[9] https://jcristharif.com/msgspec

[10] https://omegaconf.readthedocs.io/en/2.3_branch/usage.html

[11] https://rich.readthedocs.io/en/stable/console.html

[12] https://beartype.readthedocs.io/en/latest/api_decor

[13] https://docs.python.org/3/library/os.html

[14] https://rich.readthedocs.io/en/stable/reference/console.html
