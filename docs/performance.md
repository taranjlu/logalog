# Performance

This page records the startup and call cost of logalog.
Use it to check the CLI hook path and to compare changes.

## Method

Run the benchmark from the repository root:

```bash
uv run python scripts/benchmark.py
```

The script starts a fresh interpreter for each value. Each value is the median of seven processes.
Log output goes to the null device, so terminal speed does not change the results.

- `import logging` and `import logalog` use the cumulative time from `python -X importtime`.
  The bytecode cache is warm.
- The first call values start after import. They include configuration, backend setup,
  one `info` call, and `flush()`.
- The per-call values use synchronous delivery and one thread.
  A suppressed `debug` call uses the default controls. An emitted `info` call renders with Rich.
- The thread values use 8 threads with 250 `info` calls each, then `flush()`.

The host is Linux with 12 CPUs and Python 3.14.6. Background load changes values by up to about 10% between runs.

## Targets

- `import logalog` within about 2 times `import logging`.
- A suppressed `debug` call in the low microseconds.

## Baseline

Commit `8e887f4a` is the reviewed code. The fixes commit adds the correctness fixes.

| Measurement | `8e887f4a` | Fixes |
| --- | ---: | ---: |
| import logging (ms) | 12.1 | 12.2 |
| import logalog (ms) | 123.6 | 121.1 |
| first synchronous call (ms) | 3.8 | 3.7 |
| first queued call and flush (ms) | 8.1 | 7.5 |
| suppressed debug call (µs) | 5.0 | 4.9 |
| emitted info call (µs) | 251.5 | 246.5 |
| 8 threads, synchronous (records/s) | 2,522 | 2,409 |
| 8 threads, queued (records/s) | 2,696 | 2,461 |

The fixes do not change the cost in a significant way.
Rich rendering of the stderr line is most of the emitted call cost.

## Round 1: remove Beartype

Change: remove Beartype from all modules and from the runtime dependencies.
The owner approved this change if measurements showed a cost.
Explicit checks remain for redaction inputs, file destinations, configuration controls,
prefixes, and module names.

| Measurement | Before | After |
| --- | ---: | ---: |
| import logalog (ms) | 121.1 | 81.7 |
| first synchronous call (ms) | 3.7 | 3.8 |
| first queued call and flush (ms) | 7.5 | 7.4 |
| suppressed debug call (µs) | 4.9 | 3.6 |
| emitted info call (µs) | 246.5 | 242.1 |
| 8 threads, synchronous (records/s) | 2,409 | 2,568 |
| 8 threads, queued (records/s) | 2,461 | 2,550 |

Import is about 39 ms faster. Each suppressed call is about 1.3 µs faster, because
the wrapper of each public method and of `_emit` is gone.

## Round 2: load Loguru, Rich, and the parsers on first use

Change: import only light modules in `logalog`. The backend module loads Loguru and Rich
when the first record needs them. TOML and YAML parsers load only for those paths.
`FileDestination` moves to the configuration module, so the public names stay light.

| Measurement | Before | After |
| --- | ---: | ---: |
| import logalog (ms) | 81.7 | 14.3 |
| first synchronous call (ms) | 3.8 | 60.9 |
| first queued call and flush (ms) | 7.4 | 65.5 |
| suppressed debug call (µs) | 3.6 | 3.5 |
| emitted info call (µs) | 242.1 | 244.0 |
| 8 threads, synchronous (records/s) | 2,568 | 2,661 |
| 8 threads, queued (records/s) | 2,550 | 2,530 |

`import logalog` is now within about 1.1 times `import logging` (13.3 ms in this run).
The first record now pays the Loguru and Rich import cost. Import plus the first
synchronous record is 75 ms, against 85 ms before. A process that emits no record,
such as a hook with only suppressed calls, saves about 67 ms.

## Round 3: automatic delivery

Change: the owner chose automatic delivery. A logger writes in the calling thread until
`LOG.initialize()` selects the queue for worker processes. `synchronous=True` or
`synchronous=False` still fixes one mode.

This round adds two rows to the benchmark. "Hook process with one record" is the wall
time of a fresh process that imports logalog, emits one `info` record, and exits.
"First call, default delivery" uses `LOG.configure(synchronous=None)`.
The "Before" column is a new run of the round 2 code with these rows.

| Measurement | Before | After |
| --- | ---: | ---: |
| import logalog (ms) | 14.2 | 15.0 |
| hook process with one record (ms) | 113.0 | 108.2 |
| first call, default delivery (ms) | 65.6 | 62.4 |
| first synchronous call (ms) | 63.1 | 62.2 |
| first queued call and flush (ms) | 67.2 | 66.1 |
| suppressed debug call (µs) | 3.5 | 3.5 |
| emitted info call (µs) | 243.4 | 240.7 |
| 8 threads, synchronous (records/s) | 2,623 | 2,529 |
| 8 threads, queued (records/s) | 2,556 | 2,560 |

A one-record hook process is about 5 ms faster. It also no longer starts the writer
thread or the `multiprocessing` resource tracker process. Other values do not change.

## Round 4: read only the controls that decide a call

Change: each call reads only the controls that can suppress it. A `debug` or `trace` call
reads the debug control first. It stops there when debug output is off. Silence is read
only for records that the category controls accept. The control names and their
stored-default keys are cached per module.

A profile of the round 3 code showed that control resolution took 3.05 µs of the 3.5 µs
suppressed call. Each `os.environ.get` took about 0.34 µs, and each call read six names.

| Measurement | Before | After |
| --- | ---: | ---: |
| import logalog (ms) | 15.0 | 13.5 |
| hook process with one record (ms) | 108.2 | 94.2 |
| first call, default delivery (ms) | 62.4 | 56.0 |
| suppressed debug call (µs) | 3.5 | 1.4 |
| emitted info call (µs) | 240.7 | 233.0 |
| 8 threads, synchronous (records/s) | 2,529 | 3,038 |
| 8 threads, queued (records/s) | 2,560 | 2,772 |

The suppressed debug call is now 1.4 µs. This change does not touch import or backend
setup, so the lower import, hook, and first-call values in this run show run-to-run
variation of about 10%. An invalid verbose or debug value now raises only when a call reads it.

## Round 5: remove Configurator and make PyYAML optional

Change: a 20-line recursive merge replaces Configurator. It merges mappings and replaces
lists and scalar values on purpose. PyYAML moves to the optional `yaml` extra.
A YAML path without the extra raises `ConfigurationError` that names the extra.

| Measurement | Before | After |
| --- | ---: | ---: |
| import logalog (ms) | 13.5 | 12.3 |
| hook process with one record (ms) | 94.2 | 92.8 |
| first call, default delivery (ms) | 56.0 | 54.9 |
| suppressed debug call (µs) | 1.4 | 1.3 |
| emitted info call (µs) | 233.0 | 234.2 |
| 8 threads, synchronous (records/s) | 3,038 | 2,946 |
| 8 threads, queued (records/s) | 2,772 | 2,686 |

Import is about 1 ms faster and now equals `import logging` (12.1 ms in this run).
The runtime dependencies are now Loguru and Rich only.

## Output modes

The `plain` and `json` stderr modes do not load Rich for plain messages.
The benchmark has two rows for the `json` mode. Both use the code after round 5.

| Measurement | `rich` | `json` |
| --- | ---: | ---: |
| hook process with one record (ms) | 92.4 | 58.5 |
| emitted info call (µs) | 232.3 | 12.5 |

A CLI hook that uses `json` or `plain` saves about 34 ms per process.
Most of the remaining hook time is interpreter startup and the Loguru import.
Loguru imports `asyncio` at load time.
