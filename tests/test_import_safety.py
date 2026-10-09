"""Protect the import contract before the logging API grows."""

import subprocess
import sys


def test_import_has_no_output_or_worker_threads() -> None:
    """Keep package import silent, free of new threads, and free of heavy modules."""
    code = """
import sys
import threading

before = set(threading.enumerate())
import logalog
assert set(threading.enumerate()) == before
assert not {"loguru", "rich", "yaml"} & set(sys.modules), sys.modules.keys()
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
