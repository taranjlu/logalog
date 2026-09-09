# malideiter build checklist

Status: Chunk 1 is complete. Later chunks remain planned work.

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

## 2. Queued delivery and shutdown

- [ ] Make queued delivery the default. Keep the synchronous override.
- [ ] Add queue ownership, worker initialization, flush, and shutdown behavior.
- [ ] Test threads and supported process start methods for lost or duplicate records and shutdown failures.

Result: the core delivery system works before more output features enter the library.

## 3. Live logging controls

- [ ] Add independent verbose, debug, and silence controls, globally and per module.
- [ ] Generate module variable names and provide a helper to discover them.
- [ ] Read applicable environment values on every call. Test value changes, inheritance, and check overhead.

Result: environment changes affect the next call without reload. Cache names, not environment values or filter decisions.

## 4. File destinations

- [ ] Add text and JSON Lines files alongside console output.
- [ ] Use native Loguru rotation, retention, compression, and file-opening options.
- [ ] Test one writer per shared file, readable records, rotation, and failure handling.

Result: terminal and file destinations use the same event data and live controls.
Defer MessagePack until this path works.

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
