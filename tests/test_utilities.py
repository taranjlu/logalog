"""Verify logging sections, decorators, and command display."""

import asyncio
import inspect
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, cast

import pytest
from beartype.roar import BeartypeCallHintParamViolation
from rich.text import Text

from logalog import FileDestination
from logalog._backend import _RICH_SNAPSHOT
from logalog._logger import Logger, _quote_command, _Section


def test_nested_sections_reach_console_text_json_and_queue(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Indent nested records and snapshot their structured context."""
    text = tmp_path / "sections.log"
    structured = tmp_path / "sections.jsonl"
    log = Logger(files=(FileDestination(text), FileDestination(structured, kind="json")))
    with log.section("outer"):
        log.info("literal {brace}")
        with log.section("inner"):
            log.info("nested")
            log.info(Text("rich-nested", style="red"))
    log.shutdown()

    output = capsys.readouterr().err
    assert "literal {brace}" in output
    assert "  ▶ inner" in output
    assert "  nested" in output
    assert "  rich-nested" in output
    assert "  ✓ inner" in output
    assert "  nested" in text.read_text()
    records = [json.loads(line)["record"] for line in structured.read_text().splitlines()]
    nested = next(record for record in records if record["message"] == "  nested")
    assert nested["extra"] == {
        "section": "inner",
        "section_depth": 2,
        "section_parent": "outer",
    }


def test_sections_isolate_threads_and_tasks() -> None:
    """Keep each concurrent execution context separate."""
    log = Logger(synchronous=True)
    records = []
    log._get_backend().add(records.append, format="{message}")

    def thread(value: str) -> None:
        with log.section(value):
            log.info("thread")

    async def task(value: str) -> None:
        with log.section(value):
            await asyncio.sleep(0)
            log.info("task")

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(thread, ("one", "two")))

    async def tasks() -> None:
        await asyncio.gather(task("three"), task("four"))

    asyncio.run(tasks())
    log.shutdown()

    pairs = {
        (record.record["message"], record.record["extra"].get("section"))
        for record in records
        if record.record["message"] in {"thread", "task"}
    }
    assert pairs == {("thread", "one"), ("thread", "two"), ("task", "three"), ("task", "four")}


@pytest.mark.parametrize("queued", [False, True])
def test_failure_and_cancellation_log_and_restore(
    queued: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    """Propagate errors and clear their section context."""
    log = Logger(synchronous=not queued)
    records = []
    log._get_backend().add(records.append, format="{message}")
    with pytest.raises(ValueError, match="failure-marker"):
        with log.section("failed"):
            raise ValueError("failure-marker")

    async def cancel() -> None:
        with log.section("cancelled"):
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(cancel())
    log.info("after")
    log.shutdown()
    output = capsys.readouterr().err
    assert "ValueError: failure-marker" in output
    assert "CancelledError" in output
    after = next(record.record for record in records if record.record["message"] == "after")
    assert after["extra"] == {}


def test_section_logging_failures_restore_context_and_preserve_body_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Restore context and keep the original body exception."""
    log = Logger(synchronous=True)
    section = log.section("failed")
    monkeypatch.setattr(
        log, "_emit", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("enter"))
    )
    with pytest.raises(OSError, match="enter"):
        section.__enter__()
    assert log._sections.get() == ()

    monkeypatch.undo()
    monkeypatch.setattr(
        log,
        "_emit",
        lambda *args, **kwargs: (
            (_ for _ in ()).throw(OSError("exit")) if args[0] == "ERROR" else None
        ),
    )
    with pytest.raises(ValueError, match="body"):
        with section:
            raise ValueError("body")
    assert log._sections.get() == ()

    monkeypatch.undo()
    monkeypatch.setattr(
        log,
        "_emit",
        lambda *args, **kwargs: (
            (_ for _ in ()).throw(OSError("exit")) if args[0] == "ERROR" else None
        ),
    )
    with pytest.raises(asyncio.CancelledError):
        with section:
            raise asyncio.CancelledError
    assert log._sections.get() == ()

    monkeypatch.undo()
    with pytest.raises(OSError, match="exit"):
        with section:
            monkeypatch.setattr(
                log, "_emit", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("exit"))
            )
    assert log._sections.get() == ()
    log.shutdown()


def test_section_rejects_reentry_and_supports_sequential_reuse() -> None:
    """Reject one active instance and permit reuse after exit."""
    log = Logger(synchronous=True)
    section = log.section("reuse")
    with section:
        with pytest.raises(RuntimeError, match="already active"):
            section.__enter__()
    with section:
        pass
    with pytest.raises(RuntimeError, match="not active"):
        section.__exit__(None, None, None)
    with pytest.raises(BeartypeCallHintParamViolation):
        cast(Any, _Section.__exit__)(section, "bad", None, None)
    log.shutdown()


def test_elapsed_timer_uses_monotonic(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Show deterministic monotonic section time."""
    ticks = iter((4.0, 5.25))
    monkeypatch.setattr("logalog._logger.monotonic", lambda: next(ticks))
    log = Logger(synchronous=True)
    records = []
    log._get_backend().add(records.append, format="{message}")
    with log.section("timed", elapsed=True):
        pass
    log.shutdown()
    assert "✓ timed (1.250 s)" in capsys.readouterr().err


def test_sync_and_async_decorators_preserve_behavior_and_metadata(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Preserve signatures, returns, coroutine status, and exceptions."""
    log = Logger(synchronous=True)
    records = []
    log._get_backend().add(records.append, format="{message}")

    @log
    def add(left: int, right: int = 1) -> int:
        return left + right

    @log(elapsed=True)
    async def double(value: int) -> int:
        await asyncio.sleep(0)
        return value * 2

    @log
    def fail() -> None:
        raise LookupError("decorator-failure")

    assert add(2, right=3) == 5
    assert inspect.signature(add) == inspect.signature(inspect.unwrap(add))
    assert inspect.iscoroutinefunction(double)
    assert asyncio.run(double(3)) == 6
    with pytest.raises(LookupError, match="decorator-failure"):
        fail()
    log.shutdown()
    output = capsys.readouterr().err
    assert "▶" in output
    assert "decorator-failure" in output
    assert records[0].record["message"].endswith(".<locals>.add")
    assert (
        records[0].record["function"]
        == "test_sync_and_async_decorators_preserve_behavior_and_metadata"
    )


def test_decorator_rejects_generators() -> None:
    """Reject unsupported lazy function types at decoration time."""
    log = Logger(synchronous=True)

    def values():
        yield 1

    async def async_values():
        yield 1

    with pytest.raises(TypeError, match="generator"):
        log(values)
    with pytest.raises(TypeError, match="generator"):
        log(async_values)
    log.shutdown()


def test_command_quotes_redacts_and_never_executes(capsys: pytest.CaptureFixture[str]) -> None:
    """Log only a safely redacted, platform-quoted argument vector."""
    log = Logger(synchronous=True)
    records = []
    log._get_backend().add(records.append, format="{message}")
    log.command(
        ["tool", "two words", "secret", "secret"],
        redact_indices=(2,),
        redact_values=("secret", "/secret/work"),
        cwd=Path("/secret/work"),
    )
    log.shutdown()
    output = capsys.readouterr().err
    assert "$ tool 'two words'" in output
    assert output.count("[REDACTED]") == 3
    assert "secret" not in output
    assert "cwd: '[REDACTED]'" in output
    assert records[-1].record["extra"]["command"] == (
        "tool",
        "two words",
        "[REDACTED]",
        "[REDACTED]",
    )
    assert records[-1].record["extra"]["cwd"] == "[REDACTED]"


def test_section_formats_before_metadata_and_indents_every_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Keep caller formatting and indent plain and styled lines."""
    path = tmp_path / "sections.jsonl"
    log = Logger(synchronous=True, files=(FileDestination(path, kind="json"),))
    captured = []
    log._get_backend().add(captured.append, format="{message}")
    try:
        raise RuntimeError("brace-marker")
    except RuntimeError:
        with log.section("outer"):
            with log.section("inner"):
                log.exception("literal {brace}")
                log.info("{}\n\n{}", "plain-one", "plain-two", field="kept")
                log.info(Text("rich-one\n\nrich-two", style="red"))
                log.info(Text("rich-no-newline", end=""))
    log.shutdown()

    output = capsys.readouterr().err
    assert "  literal {brace}" in output
    records = [json.loads(line)["record"] for line in path.read_text().splitlines()]
    literal = next(record for record in records if "literal" in record["message"])
    plain = next(record for record in records if "plain-one" in record["message"])
    rich = next(record for record in records if "rich-one" in record["message"])
    no_newline = next(record for record in records if "rich-no-newline" in record["message"])
    assert literal["message"] == "  literal {brace}"
    assert plain["message"] == "  plain-one\n  \n  plain-two"
    assert rich["message"] == "  rich-one\n  \n  rich-two"
    assert no_newline["message"] == "  rich-no-newline"
    assert plain["extra"]["field"] == "kept"
    snapshot = next(
        record.record[_RICH_SNAPSHOT]
        for record in captured
        if record.record[_RICH_SNAPSHOT] is not None
    )
    assert isinstance(snapshot, Text)
    assert snapshot.plain == "  rich-one\n  \n  rich-two"
    assert snapshot.spans


def test_command_windows_validation_and_runtime_types(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Use Windows quoting and reject unsafe requests before output."""
    log = Logger(synchronous=True)
    assert _quote_command(["tool", "two words"], windows=True) == 'tool "two words"'
    for arguments, expected in [
        ([], ValueError),
        ("tool", ValueError),
        (["tool", 2], (TypeError, BeartypeCallHintParamViolation)),
    ]:
        with pytest.raises(expected):
            log.command(arguments)  # ty: ignore[invalid-argument-type]
    with pytest.raises(IndexError):
        log.command(["tool", "secret"], redact_indices=(2,))
    with pytest.raises(TypeError):
        log.command(["tool"], redact_indices=(True,))
    with pytest.raises((TypeError, BeartypeCallHintParamViolation)):
        log.command(["tool"], redact_values=(1,))  # ty: ignore[invalid-argument-type]
    with pytest.raises(TypeError):
        cast(Any, Logger.command).__wrapped__(log, ["tool", 2])
    with pytest.raises(TypeError):
        cast(Any, Logger.command).__wrapped__(log, ["tool"], redact_values=(1,))
    with pytest.raises(BeartypeCallHintParamViolation):
        log.section(1)  # ty: ignore[invalid-argument-type]
    with pytest.raises(ValueError, match="title"):
        log.section("")
    assert capsys.readouterr() == ("", "")
    log.shutdown()


def test_suppressed_utilities_do_not_initialize(monkeypatch: pytest.MonkeyPatch) -> None:
    """Apply live controls before utility records reach the backend."""
    log = Logger()
    monkeypatch.setenv("LOGALOG_SILENT", "1")
    with log.section("hidden"):
        log.info("hidden-body")
    log.command(["hidden-command"])
    assert log._backend is None
    log.shutdown()
