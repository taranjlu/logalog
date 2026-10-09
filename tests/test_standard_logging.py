"""Verify the optional takeover of standard logging records."""

import json
import subprocess
import sys


def test_takeover_routes_standard_records_and_restores_root() -> None:
    """Apply logalog controls to standard records and restore the root on shutdown."""
    script = r"""
import io, logging, os
from logalog import LOG, environment_names

stream = io.StringIO()
previous = logging.StreamHandler(stream)
root = logging.getLogger()
root.addHandler(previous)
root.setLevel(logging.WARNING)

LOG.configure(standard_logging=True)
assert root.level == logging.INFO
LOG.configure(standard_logging=False)
os.environ["LOGALOG_VERBOSE"] = "1"
LOG.configure(standard_logging=True)
assert root.level == 15
LOG.configure(standard_logging=False)
del os.environ["LOGALOG_VERBOSE"]
assert root.handlers == [previous] and root.level == logging.WARNING
# A debug control must be on before the takeover, so the root accepts debug records.
os.environ[environment_names("visible.lib")["module_debug"]] = "1"
LOG.configure(stderr="json", standard_logging=True)
assert previous not in root.handlers and root.level == logging.NOTSET

logging.getLogger("uvicorn.error").info("server %s", "started")
logging.getLogger("visible.lib").debug("library debug")
logging.getLogger("psycopg").debug("hidden-debug")
logging.getLogger("app").log(5, "hidden-trace")
os.environ[environment_names("uvicorn.access")["module_silent"]] = "1"
logging.getLogger("uvicorn.access").info("GET /hidden-path?token=1")
os.environ["LOGALOG_DEBUG"] = "invalid"
logging.getLogger("app").debug("hidden-invalid-control")
del os.environ["LOGALOG_DEBUG"]
try:
    raise ValueError("failure-marker")
except ValueError:
    logging.getLogger("app").exception("request failed")
LOG.shutdown()

assert root.handlers == [previous] and root.level == logging.WARNING
logging.getLogger("after").warning("after-shutdown")
assert stream.getvalue() == "after-shutdown\n", stream.getvalue()
"""
    result = subprocess.run(  # noqa: S603 -- Fixed test script without a shell.
        [sys.executable, "-I", "-c", script],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    # An invalid control reaches the standard error handler, not the application.
    assert "--- Logging error ---" in result.stderr
    assert "Invalid Boolean value for LOGALOG_DEBUG" in result.stderr
    lines = result.stderr.splitlines()
    records = [json.loads(line) for line in lines if line.startswith("{")]
    assert not any("hidden" in json.dumps(record) for record in records)
    assert [(record["name"], record["level"], record["message"]) for record in records] == [
        ("uvicorn.error", "INFO", "server started"),
        ("visible.lib", "DEBUG", "library debug"),
        ("app", "ERROR", "request failed"),
    ]
    assert records[0]["function"] == "<module>"
    assert records[2]["exception"]["type"] == "ValueError"
    assert "failure-marker" in records[2]["exception"]["traceback"]
