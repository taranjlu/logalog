# logalog build checklist

Status: Chunks 1 through 7, the review fixes, and the release preparation are complete.

Use this checklist for execution order. Keep the [longer plan](plan.md) as reference material.
Build one working layer at a time. Resolve only the decisions that the current layer needs.

## 1. Core logging path — complete

- [x] Add Loguru, Rich, and Beartype, with typed `LOG` methods.
- [x] Connect `LOG` to Loguru and one reusable Rich console on stderr.
- [x] Preserve message data and caller information without a large custom event framework.
- [x] Test ordinary messages, exceptions, runtime type checks, and safe handler setup.

Result: `from logalog import LOG` works. Messages appear once, and unrelated application handlers remain unchanged.
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

## 5. Configuration loading — complete

- [x] Compare configuration libraries against the working core and choose one.
- [x] Add explicit `pyproject.toml`, TOML, YAML, and JSON input with typed validation and defined merge rules.
- [x] Test source priority and confirm that stored settings do not disable live environment checks.

Result: configuration selects existing behavior. It does not introduce a second logging system.
XML is outside the required formats. Configurator handles recursive mapping merges
with list replacement. Separate parser adapters provide strict source validation.

Verification: 139 tests pass with 100% line and branch coverage on Python 3.11
through 3.14 and in an isolated wheel installation. Tests include stored worker
defaults, live overrides, source errors, file-list replacement, and fixed path origins.
Formatting, lint, types, builds, mechanical writing checks, and independent review pass.
The runtime dependency audit found no known vulnerabilities.

## 6. Rich content and optional encoding — complete

- [x] Add tables, code blocks, multiline layouts, and wrapping.
- [x] Test content across queues, terminals, text files, and structured output.
- [x] Assess MessagePack. Defer it because native file management is not available.

Result: advanced content uses the established delivery and destination layers.

Chunk 6 decisions: Render each accepted Rich object in the producer before queue
submission. Send the styled snapshot to the Rich console. Send its plain text to native
text and JSON Lines sinks. This rule prevents later mutation and supports Rich objects
that Python cannot pickle. Live controls suppress records before rendering.

MessagePack remains deferred. A disposable Loguru 0.7.3 test confirmed that callable
binary sinks reject `rotation`, `retention`, and `compression`. A native path sink writes
text and cannot write `msgspec` bytes. Supporting MessagePack with these guarantees
would need custom binary file rotation, retention, and compression. This design is
outside the file-ownership rule.

A host test passed the `msgspec` encoding round trip
and confirmed the native sink restrictions in both delivery modes. Add MessagePack only if Loguru adds
native binary path encoding or another small integration keeps all native file and
shutdown guarantees.

## 7. Logging utilities — complete

- [x] Add nested section contexts and elapsed time, with separate context for concurrent tasks.
- [x] Add function decorators that preserve return values, exceptions, and async behavior.
- [x] Add command display with quoting and redaction, without command execution.

Result: utilities build on the core instead of changing its delivery rules.

Verification: 163 tests pass with 100% line and branch coverage on Python 3.11
through 3.14 and in an isolated wheel installation. Formatting, lint, types,
builds, and mechanical writing checks pass. Independent review found no blocking
issues. The README documents type-error and command-display limits.

## Integration verification

The runnable example combines configuration merging, live controls, concurrent
sections, Rich tables, command redaction, exception recovery, and shutdown.
Tests run it in queued and synchronous modes.

Async decorator lifecycle records now use the decorated function's source module.
This rule also selects the correct live module controls. Body records keep their
own source locations. Tests cover partial functions, failures, and cancellation.

Verification: 173 tests pass with 100% line and branch coverage on Python 3.11
through 3.14 and against an isolated wheel. The source archive contains the
example files but excludes generated example logs. The runtime dependency audit
found no known vulnerabilities. Independent review and mechanical writing checks pass.

## Review fixes, performance, and service integration — complete

- [x] Fix the confirmed findings of two independent reviews.
- [x] Measure startup and call cost in rounds. Record each round in [performance](performance.md).
- [x] Add `plain` and `json` stderr modes with attached fields.
- [x] Add the optional takeover of standard `logging` as an explicit ownership policy.
- [x] Remove low-value tests that check Beartype, the image comparator, or duplicate cases.

Decisions on 2026-10-09: the owner removed Beartype and chose automatic delivery.
Delivery is synchronous until `LOG.initialize()` selects the queue for workers.
`TRACE` follows the debug control. YAML uses YAML 1.2 Booleans.
PyYAML is the optional `yaml` extra. A short merge replaces Configurator.

Result: `import logalog` takes about 12 ms, the same as `import logging`.
A suppressed `debug` call takes about 1.3 µs. A one-record hook process takes
about 58 ms with `json` stderr and about 92 ms with `rich` stderr.

Verification: 209 tests pass with 100% line and branch coverage on Python 3.11 through 3.14. The installed wheel
passes the same suite outside the checkout. Formatting, lint, types, complexity,
dependency, and unused-code checks pass.

Open items:

- Decide a delivery policy for a blocked stderr or a full queue. Calls can block now.
- Worker `flush()` has no timeout when the owner process stops.

## Release preparation — complete

- [x] Choose the MIT License and version 1.0.0. Add package metadata and classifiers.
- [x] Confirm that the name `logalog` is free on PyPI and TestPyPI.
- [x] Add Python 3.15 support. The image comparison runs in a separate uv script environment,
  so the full suite runs on every supported version.
- [x] Set the lowest tested Rich version to 13.8.1 and remove the Rich upper bound.
- [x] Export the `Logger` and `Section` types.
- [x] Add the changelog, the contributor guide, and the CI and release workflows.
- [x] Move development notes from the README to the contributor guide.

The README lists the open items above as known limitations.


- Keep each chunk usable and tested before starting the next layer.
- Add behavior tests with the code. Run formatting, lint, type, and relevant compatibility checks.
- Verify package changes with a build and isolated wheel installation.
- Keep runtime checks active. Do not expose secrets or mix diagnostics with protocol output.
- Update this checklist with verified results, not partial completion claims.
- Defer fine formatting, extra options, and release automation until the core works.

## Scope of the first approval

Start with chunk 1 only. Establish and verify the complete basic logging path.
Do not add queues, configuration-file loaders, rotating files, advanced Rich layouts, or utility APIs in that chunk.
