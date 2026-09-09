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

## Starting point

The skeleton uses the reference project's `src/` layout, `uv`, Ruff, Ty, pytest, and thin `just` commands.
It includes a type marker and a test for silent import without new worker threads.
It does not include runtime dependencies, a configuration framework, or release automation.
Python 3.11 is the initial minimum. Verify Python 3.11 through 3.14 before claiming that full support range.

## Core design

### Public API and ownership

Export one stable `LOG` object. Do not make callers create a logger for each module.
Preserve the caller's full module name, source location, and bound fields through wrappers.
Provide typed methods for normal severity levels and an independent verbose channel.
Keep the supported API explicit rather than promise every Loguru method.

Propose lazy initialization on the first log call, with Rich output to standard error.
Keep import silent. Do not start a queue worker or search for configuration files during import.
Allow explicit configuration before first use, including an application-specific environment prefix.
Default the prefix to `MALIDEITER`. Do not infer it from whichever module imports first.

Loguru shares one logger, and its documentation warns about handler changes from libraries.[2]
Prototype handler ownership before implementing the public API.
Do not remove host handlers, duplicate output, or capture unrelated logs by default.
Make standard-library logging interception a later, explicit integration.

### Queued and synchronous output

Use Loguru's `enqueue=True` as the default delivery model.
Keep calls such as `LOG.info()` synchronous at the call site. They submit records for background output.
Loguru distinguishes queued handlers from coroutine sinks and provides `complete()` for shutdown.[1]
Support ordinary logging without an asyncio event loop.
Provide a configuration override for direct, synchronous output with `enqueue=False`.

Verify queue ownership, child initialization, and shutdown under supported process start methods.
Include `spawn`, `forkserver`, and `fork` where the platform provides them.
An independently started process needs an explicit connection or initialization path.
Do not claim that an import alone creates a shared queue across unrelated processes.

Define flush, close, repeated configuration, sink failure, and overload behavior.
Measure producer delay under load. A background sink does not guarantee a bounded call duration.
Document normal-shutdown guarantees and possible loss after forced termination.
Do not promise a total event order across producers.

### Rich and structured records

Use Rich for every human-readable output path, including plain terminal output without color.
Support wrapped text, multiline messages, tables, code blocks, and exceptions.
Rich's `Console` handles renderable objects and terminal properties.[11]
`RichHandler` provides text logging and traceback support.[3]
Test arbitrary object transport separately.

Keep event data separate from its terminal representation.
Prototype direct Rich objects and a small serializable content description before choosing the transport contract.
Do not assume that custom renderable objects survive queue serialization.
Define when the logger captures mutable content, and test changes after the log call.
Render at the output destination where practical so wrapping uses its width.

Give each event stable fields for severity, channel, message, module, context, and exception data.
Use separate output adapters for Rich, JSON Lines, and optional MessagePack.
Keep structured output free of ANSI sequences and terminal markup.

`msgspec` is an encoder and validation library, not a file format. It supports JSON and MessagePack.[9]
Assess it after the event schema exists. Do not add a second schema framework without a clear need.

Treat ordinary strings as literal text. Accept markup only through an explicit option. Escape untrusted content.
Keep exception locals and automatic argument capture off by default.
Redact sensitive fields before queue submission and output to any destination.

### Independent environment controls

Support these global environment variables:

- `<prefix>_VERBOSE`
- `<prefix>_DEBUG`
- `<prefix>_SILENT`

Use independent Boolean controls, not a severity threshold.
Loguru supports callable filters for each sink.[1]
Set its minimum sink level to admit records before the independent filter runs.

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

Generate module controls from the full module name.
A proposed readable form is `MALIDEITER_MODULE__MYAPP__WORKER_DEBUG` for `myapp.worker`.
Specify encoding and collision handling before adopting this form.
Test underscores, case differences, nested modules, and `__main__`.

Provide a public helper that accepts a module name and returns every exact environment variable name.
Also expose effective settings and their sources without revealing secrets.
Return names without module import or earlier log output.

Propose per-setting resolution from the global value through parent modules to the exact module.
An unset module value inherits. Explicit `false` can disable an inherited verbose or debug value.
Silence at a parent scope remains effective for its children.
Define accepted Boolean strings and reject invalid values with a named configuration error.

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

- Apply defaults, then the selected `pyproject.toml` section, then explicit files in caller order.
- Apply environment overrides after files and explicit API overrides last.
- Resolve module inheritance within the resulting settings, then apply the silence rules.
- Merge mappings recursively. Replace lists and scalar values by default.
- Define deletion, null values, duplicate keys, and type conflicts explicitly.
- Report the source file, setting path, and effective origin for errors.
- Do not search parent directories or load `.env` files without a defined opt-in policy.
- Use safe YAML parsing. Reject XML external entities and document type declarations.
- Define one XML schema for lists, mappings, and scalar types. Do not guess from arbitrary XML shapes.
- Disable executable configuration, arbitrary imports, and template evaluation.

## Runtime type checking

Use Beartype within library code. Limit instrumentation to this package.
Prefer explicit decorators where they keep the boundary clear.
If a package import hook is necessary, restrict its scope and make decoration failures fatal.

Beartype's documentation describes sampled container checks by default and marks `BeartypeStrategy.On` as unimplemented.[12]
Do not describe that behavior as exhaustive validation.
Verify the pinned release with wrong arguments, return values, and nested container items.
Use explicit validation where every configuration or event item must pass.

Keep annotations specific. Avoid broad `Any` types that remove useful enforcement.
Check decorator compatibility, coroutine behavior, Rich protocols, and queue serialization.
Measure runtime cost without disabling the required checks.

## Utility functions

Add utilities after the event and lifecycle contracts are stable:

- A section context manager with recursive indentation and optional elapsed time.
- Function decorators that record entry, completion, failure, and optional elapsed time.
- A subprocess command display helper that accepts an argument sequence and never executes it.

Use task-local context, such as `contextvars`, rather than a shared indentation counter.
Capture section depth, section identity, and parent identity in each event before queue submission.
Keep structured depth fields as well as visual indentation.
Restore context after exceptions and cancellation. Define context transfer to child tasks, threads, and processes.

Use a monotonic performance clock for elapsed time.
Preserve function metadata, return values, exceptions, and coroutine behavior.
Do not consume generators or log function arguments automatically.
Define generator support separately before claiming it.

For command display, provide clear quoting, wrapping, working-directory context, and explicit redaction.
Specify the display convention for each supported shell or platform.
Do not imply that one quoted command string is portable across shells.

## Execution stages

1. **Confirm the contracts.** Resolve the configuration choice, silence rules, module names, type-checking limits, and handler ownership.
2. **Prototype the main risks.** Exercise Rich content across process queues, child initialization, shutdown, and strict configuration validation.
3. **Build the core.** Add typed `LOG` methods, Rich output, queued and synchronous modes, independent filters, and lifecycle controls.
4. **Add configuration.** Implement the selected loader, each specified file format, module overrides, and settings discovery.
5. **Add structured output and utilities.** Implement JSON Lines, assess MessagePack, then add sections, timers, decorators, and command display.
6. **Verify and document.** Test the supported Python and operating-system matrix, dependency security, built wheels, and examples.

Use small behavior tests throughout. Do not impose test-driven development or a commit after every task.
Keep implementation outside this initial planning change.

## Completion checks

- One import supports ordinary use without application boilerplate.
- All verbose and debug combinations work globally and per module.
- Silence, explicit false values, module collisions, and setting precedence follow the documented contract.
- All required configuration formats produce equivalent settings and merge results.
- Threads and supported process models produce complete, non-duplicated events during controlled shutdown.
- Concurrent sections keep separate context and restore it after failures.
- Rich output wraps at narrow widths. Tables, code blocks, exceptions, and literal brackets remain readable.
- JSON Lines and MessagePack decode independently and retain context without terminal formatting.
- Type errors fail at the intended boundary. Tests cover nested invalid data, not only scalar arguments.
- Command display never executes a command or reveals fields marked for redaction.
- Formatting, linting, type checks, tests, package builds, and isolated wheel checks pass.
- Documentation passes the planned ASD-STE100 review without a false compliance claim.

## Decisions before implementation

Confirm the silence scope and whether explicit API settings may override environment controls.
Approve the module-name encoding and configuration discovery policy.
Select a configuration library after the comparison, including its secure XML path.
Resolve the Rich queue representation and Loguru handler ownership.
Define exhaustive validation boundaries and the supported platform matrix.

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
