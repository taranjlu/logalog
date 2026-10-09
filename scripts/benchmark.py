"""Measure logalog startup and log call cost in fresh processes.

Run ``uv run python scripts/benchmark.py`` from the repository root. Each value
is the median of several fresh interpreter processes. Use ``--source`` to
measure another source tree with the same interpreter.
"""

import argparse
import os
import re
import statistics
import subprocess
import sys
import time

IMPORT_TIME = re.compile(r"import time:\s+\d+\s+\|\s+(\d+)\s+\|\s+(\S+)$")

# Each probe prints one number. Log output goes to the null device.
FIRST_CALL = """
import os, sys, time
start = time.perf_counter()
from logalog import LOG
imported = time.perf_counter()
sys.stderr = open(os.devnull, "w")
LOG.configure(synchronous={synchronous})
LOG.info("first event")
LOG.flush()
print((time.perf_counter() - imported) * 1000)
"""

HOOK = """
from logalog import LOG
LOG.info("hook event")
"""

PER_CALL = """
import os, sys, time
from logalog import LOG
sys.stderr = open(os.devnull, "w")
LOG.configure(synchronous=True)
method = LOG.{method}
method("warm up")
start = time.perf_counter()
for _ in range({count}):
    method("event")
print((time.perf_counter() - start) / {count} * 1e6)
"""

THREADS = """
import os, sys, time
from concurrent.futures import ThreadPoolExecutor
from logalog import LOG
sys.stderr = open(os.devnull, "w")
LOG.configure(synchronous={synchronous})
LOG.info("warm up")
LOG.flush()

def work(_):
    for _ in range({count}):
        LOG.info("thread event")

start = time.perf_counter()
with ThreadPoolExecutor(max_workers=8) as executor:
    list(executor.map(work, range(8)))
LOG.flush()
print(8 * {count} / (time.perf_counter() - start))
"""


def _run(arguments: list[str], environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run one fresh interpreter and fail on an error.

    Parameters
    ----------
    arguments : list[str]
        Interpreter arguments after the executable.
    environment : dict[str, str]
        Process environment.

    Returns
    -------
    subprocess.CompletedProcess[str]
        Completed process with text output.
    """
    return subprocess.run(  # noqa: S603 -- Fixed probes in the current interpreter.
        [sys.executable, *arguments],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )


def _import_time(module: str, environment: dict[str, str]) -> float:
    """Return the cumulative import time of a module in milliseconds.

    Parameters
    ----------
    module : str
        Top-level module to import.
    environment : dict[str, str]
        Process environment.

    Returns
    -------
    float
        Cumulative import time from ``-X importtime``.
    """
    result = _run(["-X", "importtime", "-c", f"import {module}"], environment)
    for line in reversed(result.stderr.splitlines()):
        match = IMPORT_TIME.search(line)
        if match and match.group(2) == module:
            return int(match.group(1)) / 1000
    raise RuntimeError(f"No import time for {module}")


def _probe(code: str, environment: dict[str, str]) -> float:
    """Return the number that one probe prints.

    Parameters
    ----------
    code : str
        Python probe source.
    environment : dict[str, str]
        Process environment.

    Returns
    -------
    float
        Measured value.
    """
    return float(_run(["-c", code], environment).stdout)


def _wall_time(code: str, environment: dict[str, str]) -> float:
    """Return the wall time of a whole process in milliseconds.

    Parameters
    ----------
    code : str
        Python probe source.
    environment : dict[str, str]
        Process environment.

    Returns
    -------
    float
        Time from process start to exit, including interpreter startup.
    """
    start = time.perf_counter()
    _run(["-c", code], environment)
    return (time.perf_counter() - start) * 1000


def main() -> None:
    """Print a Markdown table of median results."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=7, help="fresh processes per value")
    parser.add_argument("--source", help="source directory to put first on sys.path")
    options = parser.parse_args()
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("LOGALOG_")
    }
    if options.source:
        environment["PYTHONPATH"] = options.source
    # Write bytecode before measuring warm imports.
    _run(["-c", "import logalog"], environment)

    measurements = {
        "import logging (ms)": lambda: _import_time("logging", environment),
        "import logalog (ms)": lambda: _import_time("logalog", environment),
        "hook process with one record (ms)": lambda: _wall_time(HOOK, environment),
        "first call, default delivery (ms)": lambda: _probe(
            FIRST_CALL.format(synchronous=None), environment
        ),
        "first synchronous call (ms)": lambda: _probe(
            FIRST_CALL.format(synchronous=True), environment
        ),
        "first queued call and flush (ms)": lambda: _probe(
            FIRST_CALL.format(synchronous=False), environment
        ),
        "suppressed debug call (µs)": lambda: _probe(
            PER_CALL.format(method="debug", count=20000), environment
        ),
        "emitted info call (µs)": lambda: _probe(
            PER_CALL.format(method="info", count=2000), environment
        ),
        "8 threads, synchronous (records/s)": lambda: _probe(
            THREADS.format(synchronous=True, count=250), environment
        ),
        "8 threads, queued (records/s)": lambda: _probe(
            THREADS.format(synchronous=False, count=250), environment
        ),
    }
    print("| Measurement | Median |")
    print("| --- | ---: |")
    for name, measure in measurements.items():
        value = statistics.median(measure() for _ in range(options.runs))
        print(f"| {name} | {value:,.1f} |", flush=True)


if __name__ == "__main__":
    main()
