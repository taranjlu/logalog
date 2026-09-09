# malideiter build checklist

Status: Chunks 1 through 4 are complete. Later chunks remain planned work.

Use this checklist for execution order. Keep the [longer plan](plan.md) as reference material.
Build one working layer at a time. Resolve only the decisions that the current layer needs.

## 1. Core logging path — complete

- [x] Add Loguru, Rich, and Beartype, with typed `LOG` methods.
- [x] Connect `LOG` to Loguru and one reusable Rich console on stderr.
- [x] Preserve message data and caller information without a large custom event framework.
- [x] Test ordinary messages, exceptions, runtime type checks, and safe handler setup.

Result: `from malideiter import LOG` works. Messages appear once, and unrelated application handlers remain unchanged.
Use synchronous delivery for this first layer. Chunk 2 establishes the queued default.

Verification: 30 tests pass on Python 3.11 through 3.14.
The same tests pass against the installed wheel outside the checkout.
Formatting, lint, types, package builds, and independent review pass.
No stdout console is necessary for this layer.

## 2. Queued delivery and shutdown — complete

- [x] Make queued delivery the default. Keep the synchronous override.
- [x] Add queue ownership, worker initialization, flush, and shutdown behavior.
- [x] Test threads and supported process start methods for lost or duplicate records and shutdown failures.

Result: the core delivery system works before more output features enter the library.

Verification: 44 tests pass with 100% line and branch coverage on Python 3.11 through 3.14.
Linux tests cover `fork`, `spawn`, and `forkserver`, including owner-only output and worker exceptions.
Tests also cover concurrent shutdown, normal interpreter exit, sink failures, and serialization failures.
The installed wheel passes the same full suite outside the checkout.

## 3. Live logging controls — complete

- [x] Add independent verbose, debug, and silence controls, globally and per module.
- [x] Generate module variable names and provide a helper to discover them.
- [x] Read applicable environment values on every call. Test value changes, inheritance, and check overhead.

Result: environment changes affect the next call without reload. Cache names, not environment values or filter decisions.

Chunk 3 decisions: Debug and verbose default to off. Silence defaults to off and
suppresses all library output. Exact module values override parent and global debug
or verbose values. Silence is cumulative. Accepted queued records keep their call-time
decision.

Environment names encode each UTF-8 module part as uppercase hex to prevent
case and underscore collisions. These decisions replace the related plan proposals for
this layer.

Verification: 73 tests pass with 100% line and branch coverage.
Tests cover live changes, inheritance, queue decisions, custom worker prefixes, and shutdown.

A disposable Python 3.11.15 benchmark measured 6.64 µs for a suppressed short-module call and 13.46 µs for a deep module.
Enabled calls to a null sink took 13.99 µs and 21.12 µs.
The fixed-decision baseline took 8.66 µs enabled and 1.57 µs suppressed.
Each result is the median of three runs of 20,000 calls.
Two calls with two environment updates took 22.35 µs. Measurements exclude Rich rendering and terminal I/O.

## 4. File destinations — complete

- [x] Add text and JSON Lines files alongside console output.
- [x] Use native Loguru rotation, retention, compression, and file-opening options.
- [x] Test one writer per shared file, readable records, rotation, and failure handling.

Result: terminal and file destinations use the same event data and live controls.
Defer MessagePack until this path works.

Chunk 4 decisions: Configure a tuple of typed `FileDestination` values before
initialization. Files rotate at 10 MB and retain five archives by default. Each
configured path is unique. The owner creates all native sinks and queues. Workers use
the owner's queues, so only the owner writes and rotates shared files.

Verification: 90 tests pass with 100% line and branch coverage on Python 3.11 through
3.14. The installed wheel passes the same suite. Tests cover text and JSON exception
fields, console tracebacks, rotation, compression, file watching, startup cleanup,
and owner-only writes across Linux `fork`, `spawn`, and `forkserver`.
Formatting, lint, types, builds, mechanical writing checks, and independent review pass.

## 5. Configuration loading

- [ ] Compare configuration libraries against the working core and choose one.
- [ ] Add `pyproject.toml`, TOML, YAML, JSON, and XML input with typed validation and defined merge rules.
- [ ] Test source priority and confirm that stored settings do not disable live environment checks.

Result: configuration selects existing behavior. It does not introduce a second logging system.

## 6. Rich content and optional encoding

- [ ] Add tables, code blocks, multiline layouts, and wrapping.
- [ ] Test content across queues, terminals, text files, and structured output.
- [ ] Assess MessagePack through `msgspec`. Add it only after its file and shutdown behavior passes tests.

Result: advanced content uses the established delivery and destination layers.

## 7. Logging utilities

- [ ] Add nested section contexts and elapsed time, with separate context for concurrent tasks.
- [ ] Add function decorators that preserve return values, exceptions, and async behavior.
- [ ] Add command display with quoting and redaction, without command execution.

Result: utilities build on the core instead of changing its delivery rules.

## Rules for every chunk

- Keep each chunk usable and tested before starting the next layer.
- Add behavior tests with the code. Run formatting, lint, type, and relevant compatibility checks.
- Verify package changes with a build and isolated wheel installation.
- Keep runtime checks active. Do not expose secrets or mix diagnostics with protocol output.
- Update this checklist with verified results, not partial completion claims.
- Defer fine formatting, extra options, and release automation until the core works.

## Scope of the first approval

Start with chunk 1 only. Establish and verify the complete basic logging path.
Do not add queues, configuration-file loaders, rotating files, advanced Rich layouts, or utility APIs in that chunk.
