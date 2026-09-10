"""Verify Rich content through the existing logging pipeline."""

import json
import multiprocessing
import subprocess
import sys
from pathlib import Path

import pytest
from rich.console import Console, ConsoleOptions, Group, RenderResult
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from malideiter import FileDestination
from malideiter._logger import Logger


def _table(value: str = "complete") -> Table:
    """Build a small styled table."""
    table = Table(title="Tasks")
    table.add_column("State", style="green")
    table.add_row(value)
    return table


@pytest.mark.parametrize("synchronous", [False, True])
def test_rich_layout_reaches_console_text_and_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], synchronous: bool
) -> None:
    """Keep styled terminal content and plain destination records."""
    text_path = tmp_path / "rich.log"
    json_path = tmp_path / "rich.jsonl"
    log = Logger(
        synchronous=synchronous,
        files=(FileDestination(text_path), FileDestination(json_path, kind="json")),
    )
    content = Group(
        Text("[red]literal[/red]", style="bold red"),
        _table(),
        Syntax("value = '{literal}'", "python"),
    )
    log.info(content, task=17)
    log.shutdown()

    console = capsys.readouterr()
    text = text_path.read_text()
    record = json.loads(json_path.read_text())["record"]
    for marker in ("[red]literal[/red]", "Tasks", "complete", "value = '{literal}'"):
        assert marker in console.err
        assert marker in text
        assert marker in record["message"]
    assert console.err.count("Tasks") == 1
    assert console.out == ""
    assert "\x1b" not in text
    assert record["extra"] == {"task": 17}
    assert record["function"] == "test_rich_layout_reaches_console_text_and_json"


def test_rich_snapshot_precedes_queue_and_mutation(capsys: pytest.CaptureFixture[str]) -> None:
    """Freeze mutable content before an accepted queued call returns."""
    content = _MutableRenderable("before-mutation")
    log = Logger()
    log.info(content)
    content.value = "after-mutation"
    log.info(Text("second-rich-call"))
    log.shutdown()

    output = capsys.readouterr().err
    assert "before-mutation" in output
    assert "after-mutation" not in output
    assert "second-rich-call" in output


class _MutableRenderable:
    """Provide content that can change after a log call."""

    def __init__(self, value: str) -> None:
        self.value = value

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        """Render the current value."""
        yield self.value


class _ObservedRenderable:
    """Expose render timing and failures to tests."""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        """Count producer rendering and optionally fail."""
        self.calls += 1
        if self.fail:
            raise ValueError("render-error-marker")
        yield Text("rendered-once")


def test_suppression_happens_before_rich_rendering(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Do no Rich work for a suppressed event."""
    content = _ObservedRenderable(fail=True)
    log = Logger()
    monkeypatch.setenv("MALIDEITER_SILENT", "1")
    log.info(content)
    assert content.calls == 0
    assert log._backend is None
    log.shutdown()
    assert capsys.readouterr() == ("", "")


def test_render_error_rejects_event_before_backend() -> None:
    """Raise producer render failures without accepting a partial event."""
    content = _ObservedRenderable(fail=True)
    log = Logger()
    with pytest.raises(ValueError, match="render-error-marker"):
        log.info(content)
    assert content.calls == 1
    assert log._backend is None
    log.shutdown()


@pytest.mark.parametrize("synchronous", [False, True])
def test_rich_exception_and_format_argument_rules(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], synchronous: bool
) -> None:
    """Keep queued traceback details and reject ambiguous Rich formatting."""
    text_path = tmp_path / "exception.log"
    json_path = tmp_path / "exception.jsonl"
    log = Logger(
        synchronous=synchronous,
        files=(FileDestination(text_path), FileDestination(json_path, kind="json")),
    )
    with pytest.raises(ValueError, match="format arguments"):
        log.info(Text("content"), "unused")
    try:
        raise RuntimeError("rich-exception-marker")
    except RuntimeError:
        log.exception(Text("rich-failure", style="red"))
    log.shutdown()

    output = capsys.readouterr().err
    assert "ERROR" in output.splitlines()[0]
    assert output.count("rich-failure") == 1
    assert "Traceback" in output
    assert "RuntimeError" in output
    assert "rich-exception-marker" in output
    assert text_path.read_text().count("rich-failure") == 1
    record = json.loads(json_path.read_text())["record"]
    assert record["message"] == "rich-failure"
    assert record["exception"]["type"] == "RuntimeError"
    assert record["extra"] == {}


@pytest.mark.parametrize("method", multiprocessing.get_all_start_methods())
def test_rich_snapshot_transfers_from_worker(tmp_path: Path, method: str) -> None:
    """Transfer a supported snapshot through the owner's native queue."""
    script = r"""
import multiprocessing as mp
import sys
from malideiter import LOG, initialize_worker
from rich.table import Table

def work(owner):
    initialize_worker(owner)
    table = Table(title="Worker table")
    table.add_column("State", style="green")
    table.add_row("worker-complete")
    LOG.info(table)
    table.add_row("late-mutation")
    LOG.flush()
    LOG.shutdown()

if __name__ == "__main__":
    mp.set_start_method(sys.argv[1])
    LOG.initialize()
    process = mp.Process(target=work, args=(LOG,))
    process.start()
    process.join(10)
    assert process.exitcode == 0
    LOG.shutdown()
"""
    path = tmp_path / "rich_worker.py"
    path.write_text(script)
    result = subprocess.run(  # noqa: S603 -- Fixed isolated test script.
        [sys.executable, str(path), method],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert result.stderr.count("Worker table") == 1
    assert result.stderr.count("worker-complete") == 1
    assert "late-mutation" not in result.stderr


@pytest.mark.parametrize("synchronous", [False, True])
def test_exception_preserves_literal_braces(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], synchronous: bool
) -> None:
    """Keep unformatted exception strings literal in every destination."""
    path = tmp_path / "literal.jsonl"
    log = Logger(synchronous=synchronous, files=(FileDestination(path, kind="json"),))
    try:
        raise RuntimeError("brace-marker")
    except RuntimeError:
        log.exception("Task {name} failed {")
        log.exception("Task {} failed", "formatted")
    log.shutdown()
    output = capsys.readouterr().err
    assert "Task {name} failed {" in output
    assert "Task formatted failed" in output
    records = [json.loads(line)["record"] for line in path.read_text().splitlines()]
    assert [record["message"] for record in records] == [
        "Task {name} failed {",
        "Task formatted failed",
    ]
    assert all(record["exception"]["type"] == "RuntimeError" for record in records)
