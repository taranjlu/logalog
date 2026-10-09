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

The host is Linux with 12 CPUs and Python 3.14.6. Background load changes small values by about 5%.

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
