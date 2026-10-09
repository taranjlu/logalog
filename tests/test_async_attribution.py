"""Verify asynchronous lifecycle source data and live module controls."""

import asyncio
import json
from collections.abc import Callable
from functools import partial
from pathlib import Path
from types import FunctionType

import pytest

from logalog import LOG, FileDestination, environment_names
from logalog._logger import Logger


async def _body(helper: Callable[[], None], error: BaseException | None) -> None:
    """Emit from a coroutine and call a function from another module."""
    await asyncio.sleep(0)
    LOG.info("body event")
    helper()
    if error is not None:
        raise error


@pytest.mark.parametrize("synchronous", [False, True])
@pytest.mark.parametrize("error", [None, ValueError("async failure"), asyncio.CancelledError()])
@pytest.mark.asyncio
async def test_async_source_and_live_controls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, synchronous: bool, error: BaseException | None
) -> None:
    """Retain lifecycle identity without overriding body or helper attribution."""
    path = tmp_path / "async.jsonl"
    log = Logger(synchronous=synchronous, files=(FileDestination(path, kind="json"),))
    module = "example.worker"
    function = FunctionType(_body.__code__, dict(_body.__globals__, LOG=log, __name__=module))
    decorated = log(function)
    silence = environment_names(module)["module_silent"]

    def helper() -> None:
        log.info("helper event")

    async def drive() -> None:
        for scheduled in (False, True):
            operation = decorated(helper, error)
            if scheduled:
                operation = asyncio.create_task(operation)
            if error is None:
                await operation
            else:
                with pytest.raises(type(error)) as caught:
                    await operation
                assert caught.value is error
        monkeypatch.setenv(silence, "1")
        await asyncio.create_task(decorated(helper, None))
        monkeypatch.setenv(silence, "0")
        await asyncio.create_task(decorated(helper, None))

    await drive()
    log.info("outside event")
    log.shutdown()
    records = [json.loads(line)["record"] for line in path.read_text().splitlines()]
    lifecycle = [record for record in records if record["message"].startswith(("▶", "✓", "✗"))]
    assert len(lifecycle) == 6
    assert all(record["name"] == module for record in lifecycle)
    assert all(record["function"] == "_body" for record in lifecycle)
    assert all(record["file"]["path"] == __file__ for record in lifecycle)
    assert all(record["module"] == "test_async_attribution" for record in lifecycle)
    assert all(record["line"] == _body.__code__.co_firstlineno for record in lifecycle)
    bodies = [record for record in records if record["message"] == "body event"]
    assert len(bodies) == 3
    assert all(record["name"] == module for record in bodies)
    helpers = [record for record in records if record["message"] == "helper event"]
    assert len(helpers) == 4
    assert all(record["name"] == __name__ for record in helpers)
    failures = [record for record in lifecycle if record["exception"] is not None]
    assert len(failures) == (0 if error is None else 2)
    if error is not None:
        assert all(record["exception"]["type"] == type(error).__name__ for record in failures)
    assert records[-1]["message"] == "outside event"
    assert records[-1]["extra"] == {}


@pytest.mark.parametrize("synchronous", [False, True])
@pytest.mark.asyncio
async def test_async_partial_preserves_source(tmp_path: Path, synchronous: bool) -> None:
    """Find source data without changing a partially bound coroutine call."""
    path = tmp_path / "partial.jsonl"
    log = Logger(synchronous=synchronous, files=(FileDestination(path, kind="json"),))

    async def task(value: str) -> str:
        return value

    decorated = log(partial(task, "result"))
    assert await decorated() == "result"
    log.shutdown()
    records = [json.loads(line)["record"] for line in path.read_text().splitlines()]
    assert len(records) == 2
    assert all(record["name"] == __name__ for record in records)
    assert all(record["function"] == "task" for record in records)
    assert all(record["line"] == task.__code__.co_firstlineno for record in records)
