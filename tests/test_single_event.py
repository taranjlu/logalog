"""Probe one logical event across console, observers, and native file sinks."""

import json
from logging import LogRecord
from pathlib import Path
from threading import Thread

import pytest
from rich.text import Text

from logalog import FileDestination
from logalog._backend import _SnapshotHandler
from logalog._logger import Logger


@pytest.mark.parametrize("synchronous", [False, True])
@pytest.mark.parametrize("rich", [False, True])
@pytest.mark.parametrize("exception", [False, True])
def test_one_event_keeps_original_metadata(
    tmp_path: Path, synchronous: bool, rich: bool, exception: bool
) -> None:
    """Retain one event identity and clean JSON fields in each destination."""
    paths = [tmp_path / "first.jsonl", tmp_path / "second.jsonl"]
    log = Logger(
        synchronous=synchronous,
        files=tuple(FileDestination(path, kind="json") for path in paths),
    )
    observed = []
    log._get_backend().add(observed.append, format="{message}")
    content = Text("one-event", style="red") if rich else "one-event"
    if exception:
        try:
            raise ValueError("original-error")
        except ValueError:
            log.exception(content, marker="accepted")
    else:
        log.info(content, marker="accepted")
    log.shutdown()
    assert len(observed) == 1
    source = observed[0].record
    assert source["message"] == "one-event"
    assert source["extra"] == {"marker": "accepted"}
    assert (source["exception"] is not None) is exception
    files = []
    for path in paths:
        lines = path.read_text().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])["record"]
        assert record["message"] == source["message"]
        assert record["extra"] == source["extra"]
        assert record["time"]["timestamp"] == source["time"].timestamp()
        assert record["line"] == source["line"]
        assert record["function"] == source["function"]
        assert (
            record["exception"] is None
            if not exception
            else record["exception"]["type"] == "ValueError"
        )
        files.append(record)
    assert files[0] == files[1]


def test_console_keeps_event_time_and_producer_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """Show the producer's time and thread, not the queue writer's."""
    records: list[LogRecord] = []
    monkeypatch.setattr(_SnapshotHandler, "emit", lambda _, record: records.append(record))
    log = Logger()
    observed = []
    log._get_backend().add(observed.append, format="{message}")
    producer = Thread(target=log.info, args=("timed-event",), name="producer-thread")
    producer.start()
    producer.join()
    log.shutdown()
    assert records[0].threadName == "producer-thread"
    assert records[0].created == observed[0].record["time"].timestamp()
