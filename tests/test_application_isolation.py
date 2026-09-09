"""Verify package isolation in fresh application processes."""

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("import_first", [False, True])
def test_application_handlers_are_unchanged(tmp_path: Path, import_first: bool) -> None:
    """Keep existing and later Loguru and standard-logging handlers independent."""
    script = r"""
import io
import logging
import sys
from loguru import logger

if sys.argv[2] == 'True':
    from malideiter import LOG
logger.remove()
application_file = logger.add(sys.argv[1], format='{message}', catch=False)
standard_stream = io.StringIO()
root = logging.getLogger()
standard_handler = logging.StreamHandler(standard_stream)
root.addHandler(standard_handler)
from malideiter import LOG
LOG.info('library-only-marker')
LOG.shutdown()
logger.info('application-only-marker')
root.warning('standard-only-marker')
assert standard_stream.getvalue() == 'standard-only-marker\n'
assert root.handlers == [standard_handler]
logger.remove(application_file)
print('application-check-passed')
"""
    application_file = tmp_path / "application.log"
    result = subprocess.run(  # noqa: S603 -- Fixed test script without a shell.
        [sys.executable, "-I", "-c", script, str(application_file), str(import_first)],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )

    assert result.stdout == "application-check-passed\n"
    assert result.stderr.count("library-only-marker") == 1
    assert "application-only-marker" not in result.stderr
    assert "standard-only-marker" not in result.stderr
    assert application_file.read_text() == "application-only-marker\n"
