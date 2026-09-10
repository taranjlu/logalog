"""Exercise the documented workflow through public APIs in a fresh process."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("synchronous", [False, True])
def test_workflow_example(tmp_path: Path, synchronous: bool) -> None:
    """Merge configuration and retain task context across all destinations."""
    source = Path(__file__).resolve().parents[1] / "examples"
    example = tmp_path / "example"
    shutil.copytree(source, example, ignore=shutil.ignore_patterns("logs", "__pycache__"))
    (example / "workflow.json").write_text(
        json.dumps({"verbose": True, "synchronous": synchronous})
    )
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("MALIDEITER_EXAMPLE_")
    }
    result = subprocess.run(  # noqa: S603 -- Run the fixed repository example.
        [sys.executable, str(example / "workflow.py")],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    text = (example / "logs/workflow.log").read_text()
    structured = (example / "logs/workflow.jsonl").read_text()
    for output in (result.stderr, text, structured):
        assert "demonstration-token" not in output
        assert "Hidden debug event" not in output
        assert "Live debug event" in output
        assert "[REDACTED]" in output
        assert "Workflow complete" in output
    assert "\x1b" not in text + structured
    records = [json.loads(line)["record"] for line in structured.splitlines()]
    messages = [record["message"].strip() for record in records]
    assert messages.count("Configuration merge enabled verbose") == 1
    assert messages.count("Live debug event") == 1
    assert messages.count("Worker completed") == 2
    workers = [record for record in records if record["message"].strip() == "Worker completed"]
    assert {
        (record["extra"]["worker_number"], record["extra"]["section"]) for record in workers
    } == {(1, "Worker 1"), (2, "Worker 2")}
    assert all(record["extra"]["section_depth"] == 3 for record in workers)
    lifecycle = [record for record in records if record["extra"].get("section") == "worker"]
    assert lifecycle
    assert all(record["file"]["name"] == "workflow.py" for record in lifecycle)
    assert all(record["name"] == "__main__" for record in lifecycle)
    commands = [record for record in records if "command" in record["extra"]]
    assert len(commands) == 1
    assert commands[0]["extra"]["command"] == ["example-tool", "--token", "[REDACTED]"]
    assert commands[0]["extra"]["cwd"] == str(example)
    failures = [record for record in records if record["exception"] is not None]
    assert len(failures) == 1
    assert failures[0]["exception"]["type"] == "ValueError"
    assert failures[0]["extra"]["section"] == "Handled failure"
    assert records[-1]["message"] == "Workflow complete"
    assert records[-1]["extra"] == {}
    assert not (tmp_path / "logs").exists()
