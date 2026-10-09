"""Verify native text and JSON Lines file destinations."""

import gzip
import json
import multiprocessing
import pickle
import subprocess
import sys
import time
from pathlib import Path
from threading import enumerate as threads
from types import SimpleNamespace

import pytest

from logalog import FileDestination
from logalog._logger import Logger


@pytest.mark.parametrize("synchronous", [False, True])
def test_text_and_json_share_fields_caller_and_exception(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], synchronous: bool
) -> None:
    """Keep one event useful in text, JSON Lines, and Rich output."""
    text_path = tmp_path / "events.log"
    json_path = tmp_path / "events.jsonl"
    log = Logger(
        synchronous=synchronous,
        files=(FileDestination(text_path), FileDestination(json_path, kind="json")),
    )
    log.info("task {task}", task=17, state="complete")
    try:
        raise ValueError("exception-marker")
    except ValueError:
        log.exception("failure-marker", task=18)
    log.shutdown()

    text = text_path.read_text()
    records = [json.loads(line)["record"] for line in json_path.read_text().splitlines()]
    console = capsys.readouterr()
    assert not console.out
    assert console.err.count("failure-marker") == 1
    assert console.err.count("Traceback") == 1
    assert console.err.count("ValueError: exception-marker") == 1
    assert text.count("task 17") == 1
    assert text.count("Traceback") == 1
    assert text.count("ValueError: exception-marker") == 1
    assert records[0]["message"] == "task 17"
    assert records[0]["extra"] == {"task": 17, "state": "complete"}
    assert records[0]["function"] == "test_text_and_json_share_fields_caller_and_exception"
    assert Path(records[0]["file"]["path"]) == Path(__file__)
    assert records[1]["exception"] == {
        "type": "ValueError",
        "value": "exception-marker",
        "traceback": True,
    }


def test_delay_open_mode_and_silence_before_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Delay creation and keep suppressed events off disk."""
    path = tmp_path / "delayed.log"
    path.write_text("old\n")
    destination = FileDestination(path, delay=True, mode="w", encoding="utf-16")
    log = Logger(synchronous=True, files=(destination,))
    assert path.read_text() == "old\n"
    monkeypatch.setenv("LOGALOG_SILENT", "1")
    log.info("hidden-marker")
    assert path.read_text() == "old\n"
    monkeypatch.delenv("LOGALOG_SILENT")
    log.info("written-marker")
    log.shutdown()
    assert "written-marker" in path.read_text(encoding="utf-16")


def test_size_rotation_retention_and_gzip(tmp_path: Path) -> None:
    """Use Loguru to rotate, retain, and compress a text file."""
    path = tmp_path / "rotating.log"
    log = Logger(
        synchronous=True,
        files=(FileDestination(path, rotation=250, retention=1, compression="gz"),),
    )
    for index in range(12):
        log.info("event-{:02d}-{}", index, "x" * 80)
    log.shutdown()

    archives = list(tmp_path.glob("rotating.*.log.gz"))
    assert len(archives) == 1
    assert "event-" in gzip.open(archives[0], mode="rt", encoding="utf8").read()
    assert path.read_text().count("event-") >= 1


def test_time_rotation_and_external_reopen(tmp_path: Path) -> None:
    """Rotate by elapsed time and reopen a replaced active file."""
    rotating = tmp_path / "timed.log"
    watched = tmp_path / "watched.log"
    log = Logger(
        synchronous=True,
        files=(
            FileDestination(rotating, rotation="1 millisecond", retention=2),
            FileDestination(watched, rotation=None, retention=None, watch=True),
        ),
    )
    log.info("first-marker")
    time.sleep(0.01)
    moved = tmp_path / "watched.old"
    watched.rename(moved)
    watched.touch()
    log.info("second-marker")
    log.shutdown()

    assert list(tmp_path.glob("timed.*.log"))
    assert "first-marker" in moved.read_text()
    assert "second-marker" not in moved.read_text()
    assert "second-marker" in watched.read_text()


@pytest.mark.parametrize(
    ("files", "message"),
    [
        ((FileDestination(""),), "empty"),
        (
            (FileDestination("same.log"), FileDestination("./same.log", kind="json")),
            "unique",
        ),
    ],
)
def test_invalid_file_paths_fail_before_setup(
    files: tuple[FileDestination, ...], message: str
) -> None:
    """Reject paths that cannot have one clear owner sink."""
    with pytest.raises(ValueError, match=message):
        Logger(files=files)


def test_invalid_destination_values_fail_before_setup(tmp_path: Path) -> None:
    """Reject destination values and types that could write to the wrong place."""
    with pytest.raises(ValueError, match="invalid kind"):
        FileDestination("events.log", kind="xml")  # ty: ignore[invalid-argument-type]
    invalid = SimpleNamespace(path=tmp_path / "invalid.log")
    with pytest.raises(TypeError, match="FileDestination"):
        Logger(files=(FileDestination(tmp_path / "valid.log"), invalid))  # ty: ignore[invalid-argument-type]


def test_native_configuration_and_write_failures_are_visible(tmp_path: Path) -> None:
    """Report invalid native options and synchronous write failures."""
    invalid = Logger(
        synchronous=True,
        files=(FileDestination(tmp_path / "bad.log", rotation="not-a-rule"),),
    )
    with pytest.raises(ValueError, match="rotation"):
        invalid.initialize()
    invalid.shutdown()

    directory = tmp_path / "directory"
    directory.mkdir()
    failed = Logger(synchronous=True, files=(FileDestination(directory),))
    with pytest.raises(IsADirectoryError):
        failed.initialize()
    failed.shutdown()


@pytest.mark.parametrize("method", multiprocessing.get_all_start_methods())
def test_workers_use_owner_file_writer(tmp_path: Path, method: str) -> None:
    """Send all worker writes and rotation through the owner handler."""
    script = r"""
import multiprocessing as mp
import sys
from logalog import FileDestination, LOG, initialize_worker

def work(owner, value):
    initialize_worker(owner)
    LOG.info("worker-{}", value)
    LOG.flush()
    LOG.shutdown()

if __name__ == "__main__":
    mp.set_start_method(sys.argv[1])
    from os import getpid
    from loguru._file_sink import FileSink
    owner_pid = getpid()
    original_write = FileSink.write
    def owner_write(sink, message):
        assert getpid() == owner_pid, "Non-owner file writer"
        original_write(sink, message)
    FileSink.write = owner_write
    LOG.configure(files=(FileDestination(sys.argv[2], rotation=300, retention=20),))
    LOG.initialize()
    processes = [mp.Process(target=work, args=(LOG, value)) for value in range(8)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(10)
        assert process.exitcode == 0
    LOG.shutdown()
"""
    path = tmp_path / "workers.log"
    script_path = tmp_path / "file_workers.py"
    script_path.write_text(script)
    result = subprocess.run(  # noqa: S603 -- Fixed isolated test script.
        [sys.executable, str(script_path), method, str(path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    output = "".join(file.read_text() for file in tmp_path.glob("workers*.log"))
    for value in range(8):
        assert output.count(f"worker-{value}") == 1


def test_queued_file_serialization_failure_keeps_later_writes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Reject an unsafe field before any destination receives the event."""
    paths = (tmp_path / "queue.log", tmp_path / "queue.jsonl")
    log = Logger(files=(FileDestination(paths[0]), FileDestination(paths[1], kind="json")))
    with pytest.raises((AttributeError, TypeError, pickle.PicklingError)):
        log.info("rejected", invalid=lambda: None)
    circular: dict[str, object] = {}
    circular["self"] = circular
    with pytest.raises(ValueError, match="Circular"):
        log.info("rejected", invalid=circular)
    log.info("accepted")
    log.shutdown()
    for output in (capsys.readouterr().err, *(path.read_text() for path in paths)):
        assert "rejected" not in output
        assert "accepted" in output
        assert len(output.splitlines()) == 1


def test_close_failure_still_closes_later_destinations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Close every destination and report the first close failure."""
    from loguru._file_sink import FileSink

    stopped = []
    original_stop = FileSink.stop

    def stop(sink: FileSink) -> None:
        stopped.append(Path(sink._path))
        original_stop(sink)
        if sink._path.endswith("first.log"):
            raise OSError("close-failure-marker")

    monkeypatch.setattr(FileSink, "stop", stop)
    paths = [tmp_path / "first.log", tmp_path / "second.log"]
    log = Logger(files=tuple(FileDestination(path) for path in paths))
    log.info("closing")
    with pytest.raises(OSError, match="close-failure-marker"):
        log.shutdown()
    assert stopped == paths
    assert not [thread for thread in threads() if thread.name.startswith("loguru-writer")]
    with pytest.raises(RuntimeError, match="shut down"):
        log.info("after-failure")


@pytest.mark.parametrize("synchronous", [False, True])
def test_partial_setup_closes_earlier_destinations(tmp_path: Path, synchronous: bool) -> None:
    """Close earlier sinks after setup fails and permit corrected configuration."""
    path = tmp_path / "partial.log"
    before = set(threads())
    log = Logger(
        synchronous=synchronous,
        files=(FileDestination(path), FileDestination(tmp_path)),
    )
    with pytest.raises(IsADirectoryError):
        log.initialize()
    assert set(threads()) == before
    assert log._backend is None
    log.configure(synchronous=synchronous, files=(FileDestination(path),))
    log.info("recovered-after-setup-error")
    log.shutdown()
    assert set(threads()) == before
    assert path.read_text().count("recovered-after-setup-error") == 1


def test_symlink_aliases_cannot_create_two_writers(tmp_path: Path) -> None:
    """Reject two destination paths that resolve to the same file."""
    path = tmp_path / "original.log"
    alias = tmp_path / "alias.log"
    alias.symlink_to(path)
    with pytest.raises(ValueError, match="unique"):
        Logger(files=(FileDestination(path), FileDestination(alias, kind="json")))
    assert not path.exists()
