"""Verify the typed logging path and its observable output."""

import inspect
import re
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from beartype import beartype
from beartype.roar import BeartypeCallHintParamViolation

from malideiter._logger import Logger

if TYPE_CHECKING:
    from loguru import Message


@pytest.fixture
def log() -> Iterator[Logger]:
    """Give each test an independent logger and close its handlers afterward."""
    instance = Logger(synchronous=True)
    yield instance
    instance.shutdown()


@pytest.mark.parametrize(
    "method", ["trace", "debug", "info", "success", "warning", "error", "critical"]
)
def test_levels_write_once_to_stderr(
    log: Logger, capsys: pytest.CaptureFixture[str], method: str
) -> None:
    """Write every supported severity once without using stdout."""
    getattr(log, method)("message-marker")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.count("message-marker") == 1
    assert method.upper() in captured.err


def test_format_arguments_and_record_fields(
    log: Logger, capsys: pytest.CaptureFixture[str]
) -> None:
    """Keep formatted text and structured fields on the same Loguru record."""
    records: list[Message] = []
    log._get_backend().add(records.append, format="{message}")

    log.info("Task {}: {state}", 17, state="complete", task_id=17)

    assert "Task 17: complete" in capsys.readouterr().err
    assert len(records) == 1
    record = records[0].record
    assert record["message"] == "Task 17: complete"
    assert record["extra"] == {"state": "complete", "task_id": 17}


def test_source_location_survives_wrappers(log: Logger) -> None:
    """Retain the exact caller module, function, file, and line."""
    records: list[Message] = []
    log._get_backend().add(records.append, format="{message}")
    frame = inspect.currentframe()
    assert frame is not None
    expected_line = frame.f_lineno + 1
    log.info("source-marker")
    del frame

    record = records[0].record
    assert record["name"] == __name__
    assert record["function"] == "test_source_location_survives_wrappers"
    assert Path(record["file"].path) == Path(__file__)
    assert record["line"] == expected_line


def test_log_method_preserves_source(log: Logger) -> None:
    """Keep caller information through the generic severity method."""
    records: list[Message] = []
    log._get_backend().add(records.append, format="{message}")

    log.log("WARNING", "generic-marker")

    assert records[0].record["function"] == "test_log_method_preserves_source"
    assert records[0].record["level"].name == "WARNING"


def test_decorated_application_caller(log: Logger) -> None:
    """Do not skip an application's own decorated function."""
    records: list[Message] = []
    log._get_backend().add(records.append, format="{message}")

    @beartype
    def application(value: str) -> None:
        log.info(value)

    application("decorated-marker")

    assert records[0].record["function"] == "application"
    assert records[0].record["name"] == __name__


def test_literal_markup_and_braces(log: Logger, capsys: pytest.CaptureFixture[str]) -> None:
    """Do not treat ordinary message text as Rich markup or a template."""
    text = "[red]literal[/red] {unresolved} <blue>unchanged</blue>"
    log.info(text)

    output = capsys.readouterr().err
    assert "[red]literal[/red]" in output
    assert "{unresolved}" in output
    assert "<blue>unchanged</blue>" in output
    assert "\x1b" not in output


def test_exception_renders_once_without_locals(
    log: Logger, capsys: pytest.CaptureFixture[str]
) -> None:
    """Render one traceback without local variable values."""
    private_value = "private-local-marker"
    try:
        raise ValueError("exception-marker")
    except ValueError:
        log.exception("failure-marker")

    output = capsys.readouterr().err
    assert output.count("failure-marker") == 1
    assert output.count("Traceback") == 1
    assert output.count("ValueError: exception-marker") == 1
    assert private_value not in output


def test_error_does_not_capture_active_exception(
    log: Logger, capsys: pytest.CaptureFixture[str]
) -> None:
    """Leave traceback capture explicit on ordinary error calls."""
    try:
        raise ValueError("not-in-output")
    except ValueError:
        log.error("ordinary-error")

    output = capsys.readouterr().err
    assert "ordinary-error" in output
    assert "not-in-output" not in output
    assert "Traceback" not in output


def test_exception_outside_handler(log: Logger, capsys: pytest.CaptureFixture[str]) -> None:
    """Allow exception logging without an active exception."""
    log.exception("no-active-exception")

    output = capsys.readouterr().err
    assert "no-active-exception" in output
    assert "Traceback" not in output


@pytest.mark.parametrize(
    "method", ["trace", "debug", "info", "success", "warning", "error", "critical", "exception"]
)
def test_invalid_message_fails_before_setup(
    log: Logger, method: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """Reject non-string messages without output or backend initialization."""
    with pytest.raises(BeartypeCallHintParamViolation):
        getattr(log, method)(42)

    assert log._backend is None
    assert capsys.readouterr() == ("", "")


def test_invalid_level_fails_before_setup(log: Logger, capsys: pytest.CaptureFixture[str]) -> None:
    """Reject unknown severity names before creating a handler."""
    with pytest.raises(BeartypeCallHintParamViolation):
        log.log("UNKNOWN", "invalid-level")  # ty: ignore[invalid-argument-type]

    assert log._backend is None
    assert capsys.readouterr() == ("", "")


def test_bad_format_does_not_write_partial_message(
    log: Logger, capsys: pytest.CaptureFixture[str]
) -> None:
    """Keep format errors visible to the caller without partial output."""
    with pytest.raises(KeyError, match="missing"):
        log.info("{missing}", present="value")

    assert capsys.readouterr() == ("", "")


def test_console_follows_stderr_redirection(log: Logger) -> None:
    """Reuse the backend while respecting later stderr redirection."""
    first, second, stdout = StringIO(), StringIO(), StringIO()
    with redirect_stdout(stdout), redirect_stderr(first):
        log.info("first-stream-marker")
    backend = log._backend
    with redirect_stdout(stdout), redirect_stderr(second):
        log.info("second-stream-marker")

    assert log._backend is backend
    assert stdout.getvalue() == ""
    assert "first-stream-marker" in first.getvalue()
    assert "second-stream-marker" not in first.getvalue()
    assert "second-stream-marker" in second.getvalue()
    assert "first-stream-marker" not in second.getvalue()


def test_concurrent_first_use_has_one_output_per_call(
    log: Logger, capsys: pytest.CaptureFixture[str]
) -> None:
    """Create one backend during concurrent first calls without duplicate output."""
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda value: log.info("thread-event-{:03d}", value), range(40)))

    captured = capsys.readouterr()
    assert captured.out == ""
    assert sorted(re.findall(r"thread-event-\d{3}", captured.err)) == [
        f"thread-event-{value:03d}" for value in range(40)
    ]
