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
