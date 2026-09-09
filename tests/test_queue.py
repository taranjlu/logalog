"""Verify queued delivery, lifecycle control, and process sharing."""

import multiprocessing
import pickle
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest

from malideiter import initialize_worker
from malideiter._logger import Logger


def test_default_queue_flush_and_shutdown(capsys: pytest.CaptureFixture[str]) -> None:
    """Flush queued output and reject calls after shutdown."""
    log = Logger()
    log.info("queued-marker")
    assert log._backend is not None
    log.flush()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "queued-marker" in captured.err
    log.shutdown()
    log.shutdown()
    log.flush()

    with pytest.raises(RuntimeError, match="shut down"):
        log.info("late-marker")


def test_synchronous_override_and_configuration(capsys: pytest.CaptureFixture[str]) -> None:
    """Allow an explicit direct writer only before setup."""
    log = Logger()
    log.configure(synchronous=True)
    log.info("direct-marker")
    assert "direct-marker" in capsys.readouterr().err

    with pytest.raises(RuntimeError, match="already fixed"):
        log.configure()
    log.shutdown()


def test_queued_exception_keeps_traceback(capsys: pytest.CaptureFixture[str]) -> None:
    """Convert a live traceback to useful queue-safe text."""
    log = Logger()
    try:
        raise ValueError("queued-exception-marker")
    except ValueError:
        log.exception("queued-failure-marker")
    log.shutdown()

    output = capsys.readouterr().err
    assert output.count("queued-failure-marker") == 1
    assert output.count("Traceback") == 1
    assert "ValueError" in output
    assert output.count("queued-exception-marker") == 1


def test_queued_threads_deliver_each_record_once(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Deliver concurrent records once before shutdown."""
    log = Logger()
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda value: log.info("queued-thread-{:03d}", value), range(40)))
    log.shutdown()

    assert sorted(re.findall(r"queued-thread-\d{3}", capsys.readouterr().err)) == [
        f"queued-thread-{value:03d}" for value in range(40)
    ]


def test_worker_initialization_rejects_invalid_owners() -> None:
    """Reject synchronous and repeated worker initialization."""
    worker = Logger()
    with pytest.raises(ValueError, match="queued delivery"):
        worker._use_worker_backend(Logger(synchronous=True))

    owner = Logger()
    worker._use_worker_backend(owner)
    with pytest.raises(RuntimeError, match="already initialized"):
        worker._use_worker_backend(owner)
    worker.shutdown()
    owner.shutdown()

    initialize_worker(__import__("malideiter").LOG)

    with pytest.raises(ValueError, match="queued delivery"):
        pickle.dumps(Logger(synchronous=True))

    unused = Logger()
    unused.flush()
    unused.shutdown()
    with pytest.raises(RuntimeError, match="already fixed"):
        unused.configure()


def test_queued_sink_failure_does_not_hang() -> None:
    """Report a queued sink failure and finish shutdown."""
    script = r"""
from rich.logging import RichHandler
from malideiter._logger import Logger

def fail(*args):
    raise OSError("sink-failure-marker")

RichHandler.emit = fail
log = Logger()
log.info("failed-event")
log.shutdown()
"""
    result = subprocess.run(  # noqa: S603 -- Fixed test script without a shell.
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert "Logging error in Loguru Handler" in result.stderr
    assert "OSError: sink-failure-marker" in result.stderr


@pytest.mark.parametrize("method", multiprocessing.get_all_start_methods())
def test_process_workers_share_owner_queue(tmp_path: Path, method: str) -> None:
    """Deliver each worker record once through the owner queue."""
    script = r"""
import multiprocessing as mp
from malideiter import LOG, initialize_worker

def work(owner, value):
    initialize_worker(owner)
    LOG.info("process-event-{}", value)
    try:
        raise ValueError(f"worker-failure-{value}")
    except ValueError:
        LOG.exception("worker-exception")
    LOG.flush()
    LOG.shutdown()

if __name__ == "__main__":
    mp.set_start_method(__import__("sys").argv[1])
    from os import getpid
    from rich.logging import RichHandler
    owner_pid = getpid()
    original_emit = RichHandler.emit
    def verify_owner(handler, record):
        assert getpid() == owner_pid, "Non-owner writer"
        original_emit(handler, record)
    RichHandler.emit = verify_owner
    LOG.initialize()
    processes = [mp.Process(target=work, args=(LOG, value)) for value in range(4)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(10)
        assert process.exitcode == 0
    LOG.info("owner-still-active")
    LOG.flush()
    LOG.shutdown()
"""
    script_path = tmp_path / "process_test.py"
    script_path.write_text(script)
    result = subprocess.run(  # noqa: S603 -- Fixed test script without a shell.
        [sys.executable, str(script_path), method],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert sorted(re.findall(r"process-event-\d", result.stderr)) == [
        f"process-event-{value}" for value in range(4)
    ]
    assert sorted(re.findall(r"worker-failure-\d", result.stderr)) == [
        f"worker-failure-{value}" for value in range(4)
    ]
    assert result.stderr.count("owner-still-active") == 1
    assert "Logging error" not in result.stderr


@pytest.mark.parametrize("failed_exit", [False, True])
def test_normal_interpreter_exit_flushes_shared_logger(failed_exit: bool) -> None:
    """Flush the shared queue at normal exit, including an unhandled exception."""
    script = "from malideiter import LOG; LOG.info('exit-marker')"
    if failed_exit:
        script += "\nraise RuntimeError('exit-failure')"
    result = subprocess.run(  # noqa: S603 -- Fixed test script without a shell.
        [sys.executable, "-I", "-c", script],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == int(failed_exit)
    assert result.stdout == ""
    assert result.stderr.count("exit-marker") == 1


def test_shutdown_waits_for_active_emission(capsys: pytest.CaptureFixture[str]) -> None:
    """Finish an accepted log call before closing its handler."""
    log = Logger()
    formatting, release, shutting_down = Event(), Event(), Event()

    class PausedValue:
        def __format__(self, spec: str) -> str:
            formatting.set()
            assert release.wait(5)
            return "accepted-event"

    def shutdown() -> None:
        shutting_down.set()
        log.shutdown()

    with ThreadPoolExecutor(max_workers=2) as executor:
        emission = executor.submit(log.info, "{}", PausedValue())
        try:
            assert formatting.wait(5)
            closing = executor.submit(shutdown)
            assert shutting_down.wait(5)
            with pytest.raises(TimeoutError):
                closing.result(timeout=0.05)
        finally:
            release.set()
        emission.result(timeout=5)
        closing.result(timeout=5)
    assert capsys.readouterr().err.count("accepted-event") == 1


def test_queued_exception_without_active_error(capsys: pytest.CaptureFixture[str]) -> None:
    """Do not add a false traceback when no exception is active."""
    log = Logger()
    log.exception("no-active-error")
    log.shutdown()
    output = capsys.readouterr().err
    assert output.count("no-active-error") == 1
    assert "NoneType" not in output
    assert "Traceback" not in output


def test_unpickleable_field_fails_without_breaking_queue(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Report a producer serialization error and keep later delivery usable."""
    log = Logger()
    with pytest.raises((AttributeError, pickle.PicklingError), match="pickle"):
        log.info("rejected-event", invalid=lambda: None)
    log.info("valid-after-rejection")
    log.shutdown()
    output = capsys.readouterr().err
    assert "rejected-event" not in output
    assert output.count("valid-after-rejection") == 1
