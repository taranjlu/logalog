"""Protect the import contract before the logging API grows."""

import subprocess
import sys


def test_import_has_no_output_or_worker_threads() -> None:
    """Keep package import silent and free of new worker threads."""
    code = """
import threading

before = set(threading.enumerate())
import malideiter
assert set(threading.enumerate()) == before
"""
    result = subprocess.run(  # noqa: S603 -- Fixed code in the test interpreter, without a shell.
        [sys.executable, "-I", "-c", code],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )

    assert result.stdout == ""
    assert result.stderr == ""
