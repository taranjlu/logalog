"""Verify the plain and JSON stderr output modes."""

import json
import subprocess
import sys

import pytest
from rich.text import Text

from logalog._logger import Logger


@pytest.mark.parametrize("synchronous", [False, True])
def test_plain_and_json_stderr_show_fields_and_tracebacks(
    capsys: pytest.CaptureFixture[str], synchronous: bool
) -> None:
    """Show attached fields, exceptions, and Rich text without terminal codes."""
    outputs = {}
    for mode in ("plain", "json"):
        log = Logger(synchronous=synchronous, stderr=mode)
        log.info("request finished", request_id="id 1", status=201, method="GET")
        try:
            raise ValueError("failure-marker")
        except ValueError:
            log.exception("request failed")
        log.info(Text("styled-marker", style="red"))
        log.shutdown()
        outputs[mode] = capsys.readouterr().err

    plain = outputs["plain"]
    assert "\x1b" not in plain
    assert '- request finished | request_id="id 1" status=201 method=GET\n' in plain
    assert "| ERROR    |" in plain
    assert "ValueError: failure-marker" in plain
    assert "styled-marker" in plain

    records = [json.loads(line) for line in outputs["json"].splitlines()]
    assert len(records) == 3
    assert records[0]["message"] == "request finished"
    assert records[0]["level"] == "INFO"
    assert records[0]["name"] == __name__
    assert records[0]["extra"] == {"request_id": "id 1", "status": 201, "method": "GET"}
    assert records[1]["exception"]["type"] == "ValueError"
    assert "ValueError: failure-marker" in records[1]["exception"]["traceback"]
    assert records[2]["message"] == "styled-marker"
    assert records[2]["exception"] is None


def test_json_mode_rejects_circular_fields_and_skips_rich() -> None:
    """Keep JSON stderr valid and leave Rich unloaded for plain messages."""
    code = """
import sys
from logalog import LOG
LOG.configure(stderr="json")
circular = {}
circular["self"] = circular
try:
    LOG.info("rejected", data=circular)
except ValueError:
    pass
LOG.info("accepted", count=1)
assert "rich" not in sys.modules
"""
    result = subprocess.run(  # noqa: S603 -- Fixed test code without a shell.
        [sys.executable, "-I", "-c", code],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    assert result.stdout == ""
    [record] = [json.loads(line) for line in result.stderr.splitlines()]
    assert record["message"] == "accepted"
    assert record["extra"] == {"count": 1}


def test_invalid_stderr_mode_fails_before_setup() -> None:
    """Reject an unknown mode instead of hiding output."""
    with pytest.raises(ValueError, match="stderr must be"):
        Logger(stderr="color")  # ty: ignore[invalid-argument-type]
