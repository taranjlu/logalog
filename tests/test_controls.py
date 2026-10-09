"""Verify live global and module logging controls."""

import os
import subprocess
import sys
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

import pytest

from logalog import ConfigurationError, environment_names
from logalog._logger import Logger


@pytest.fixture
def log() -> Iterator[Logger]:
    """Give each test a synchronous logger."""
    instance = Logger(synchronous=True)
    yield instance
    instance.shutdown()


def _call_as(log: Logger, module: str, method: str, message: str) -> None:
    """Make a call with a selected caller module."""
    exec(  # noqa: S102 -- A selected module namespace tests caller resolution.
        compile(f"log.{method}({message!r})", "caller.py", "exec"),
        {"__name__": module, "log": log},
    )


def test_names_are_discoverable_and_collision_free() -> None:
    """Return exact names without module case or underscore collisions."""
    lower = environment_names("my_app.worker")
    upper = environment_names("MY.APP", prefix="PROJECT_2")

    assert lower == {
        "global_verbose": "LOGALOG_VERBOSE",
        "global_debug": "LOGALOG_DEBUG",
        "global_silent": "LOGALOG_SILENT",
        "module_verbose": "LOGALOG_MODULE__6D795F617070__776F726B6572_VERBOSE",
        "module_debug": "LOGALOG_MODULE__6D795F617070__776F726B6572_DEBUG",
        "module_silent": "LOGALOG_MODULE__6D795F617070__776F726B6572_SILENT",
    }
    assert upper["module_debug"] == "PROJECT_2_MODULE__4D59__415050_DEBUG"
    assert upper["module_debug"] != environment_names("my.app", prefix="PROJECT_2")["module_debug"]


@pytest.mark.parametrize("module", ["", ".module", "module.", "one..two"])
def test_names_reject_empty_module_parts(module: str) -> None:
    """Reject module names that cannot form an inheritance path."""
    with pytest.raises(ValueError, match="nonempty"):
        environment_names(module)


@pytest.mark.parametrize("prefix", ["lower", "2APP", "APP-DASH", ""])
def test_prefix_is_validated(prefix: str) -> None:
    """Keep configured environment names portable and predictable."""
    with pytest.raises(ValueError, match="Prefix"):
        Logger(prefix=prefix)


@pytest.mark.parametrize("control", ["verbose", "debug"])
def test_global_controls_are_live_and_independent(
    log: Logger,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    control: str,
) -> None:
    """Apply each category control on the next call without threshold stacking."""
    method = control
    other = "debug" if control == "verbose" else "verbose"
    log.info("normal-before")
    getattr(log, method)("hidden-before")
    monkeypatch.setenv(f"LOGALOG_{control.upper()}", " YES ")
    getattr(log, method)("shown")
    getattr(log, other)("other-hidden")
    monkeypatch.setenv(f"LOGALOG_{control.upper()}", "off")
    getattr(log, method)("hidden-after")

    output = capsys.readouterr().err
    assert "normal-before" in output
    assert "shown" in output
    assert "hidden" not in output
    assert other.upper() not in output


def test_module_inheritance_override_and_silence(
    log: Logger, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Let child category values override parents but never cancel inherited silence."""
    parent = environment_names("app")
    child = environment_names("app.worker")
    monkeypatch.setenv(parent["module_verbose"], "1")
    monkeypatch.setenv(parent["module_debug"], "true")
    monkeypatch.setenv(child["module_verbose"], "0")
    _call_as(log, "app.worker", "verbose", "child-verbose-hidden")
    _call_as(log, "app.worker", "debug", "child-debug-shown")
    _call_as(log, "app.other", "verbose", "sibling-verbose-shown")
    monkeypatch.setenv(parent["module_silent"], "on")
    monkeypatch.setenv(child["module_silent"], "false")
    _call_as(log, "app.worker", "error", "child-error-hidden")
    _call_as(log, "elsewhere", "error", "other-error-shown")

    output = capsys.readouterr().err
    assert "child-debug-shown" in output
    assert "sibling-verbose-shown" in output
    assert "other-error-shown" in output
    assert "hidden" not in output


def test_global_silence_is_live_for_every_level(
    log: Logger, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Suppress all categories globally and restore them after deletion."""
    monkeypatch.setenv("LOGALOG_DEBUG", "1")
    monkeypatch.setenv("LOGALOG_VERBOSE", "1")
    monkeypatch.setenv("LOGALOG_SILENT", "true")
    for method in ("trace", "debug", "verbose", "info", "error"):
        getattr(log, method)(f"hidden-{method}")
    monkeypatch.delenv("LOGALOG_SILENT")
    log.debug("restored-debug")
    log.verbose("restored-verbose")

    output = capsys.readouterr().err
    assert "hidden" not in output
    assert "restored-debug" in output
    assert "restored-verbose" in output


@pytest.mark.parametrize("value", ["", "2", "enabled", "truth"])
def test_malformed_values_raise_before_backend(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """Reject malformed values that the call reads, with their variable name."""
    log = Logger()
    monkeypatch.setenv("LOGALOG_VERBOSE", value)
    with pytest.raises(ConfigurationError, match="LOGALOG_VERBOSE"):
        log.verbose("not-queued")
    assert log._backend is None
    log.info("verbose-control-not-read")
    log.shutdown()


def test_custom_prefix_and_queued_decision(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Use the configured prefix and keep accepted queued records."""
    log = Logger()
    log.configure(prefix="APP")
    monkeypatch.setenv("APP_VERBOSE", "on")
    log.verbose("accepted-before-silence")
    monkeypatch.setenv("APP_SILENT", "1")
    log.error("rejected-after-silence")
    log.shutdown()

    output = capsys.readouterr().err
    assert output.count("accepted-before-silence") == 1
    assert "rejected-after-silence" not in output


def test_threads_use_their_caller_module_controls(
    log: Logger, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Resolve each concurrent call from its own caller module."""
    enabled = environment_names("thread.enabled")["module_debug"]
    disabled = environment_names("thread.disabled")["module_debug"]
    monkeypatch.setenv(enabled, "1")
    monkeypatch.setenv(disabled, "0")
    calls = [
        ("thread.enabled", "shown-thread"),
        ("thread.disabled", "hidden-thread"),
    ] * 20
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(_call_as, log, module, "debug", message) for module, message in calls
        ]
        for future in futures:
            future.result()

    output = capsys.readouterr().err
    assert output.count("shown-thread") == 20
    assert "hidden-thread" not in output


def test_process_reads_its_own_environment() -> None:
    """Evaluate live controls in the process that makes the call."""
    code = """
import os
from logalog._logger import Logger
log = Logger(synchronous=True)
log.debug('hidden')
os.environ['LOGALOG_DEBUG'] = '1'
log.debug('shown')
log.shutdown()
"""
    environment = os.environ.copy()
    environment.pop("LOGALOG_DEBUG", None)
    result = subprocess.run(  # noqa: S603 -- Fixed test code without a shell.
        [sys.executable, "-I", "-c", code],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    assert result.stdout == ""
    assert "hidden" not in result.stderr
    assert result.stderr.count("shown") == 1


@pytest.mark.parametrize("control", ["verbose", "debug", "silent"])
def test_module_changes_and_deletion_restore_inheritance(
    log: Logger, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], control: str
) -> None:
    """Observe module additions, changes, and deletions without a reload."""
    name = environment_names("live.worker")[f"module_{control}"]
    monkeypatch.setenv(f"LOGALOG_{control.upper()}", "1")
    method = "info" if control == "silent" else control
    _call_as(log, "live.worker", method, "inherited")
    monkeypatch.setenv(name, "0")
    _call_as(log, "live.worker", method, "explicit-false")
    monkeypatch.setenv(name, "1")
    _call_as(log, "live.worker", method, "explicit-true")
    monkeypatch.delenv(name)
    _call_as(log, "live.worker", method, "restored-inheritance")
    monkeypatch.delenv(f"LOGALOG_{control.upper()}")
    _call_as(log, "live.worker", method, "default-state")
    output = capsys.readouterr().err
    if control == "silent":
        assert "inherited" not in output
        assert "explicit" not in output
        assert "restored-inheritance" not in output
        assert "default-state" in output
    else:
        assert "inherited" in output
        assert "explicit-false" not in output
        assert "explicit-true" in output
        assert "restored-inheritance" in output
        assert "default-state" not in output


@pytest.mark.parametrize("method", ["debug", "verbose", "info"])
def test_shutdown_rejects_suppressed_calls(monkeypatch: pytest.MonkeyPatch, method: str) -> None:
    """Keep the shutdown contract when controls would suppress the message."""
    log = Logger()
    log.shutdown()
    monkeypatch.setenv("LOGALOG_SILENT", "1")
    with pytest.raises(RuntimeError, match="shut down"):
        getattr(log, method)("after-shutdown")
    with pytest.raises(RuntimeError, match="shut down"):
        log.initialize()


def test_invalid_environment_value_is_not_disclosed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Name the invalid control without exposing its contents."""
    log = Logger()
    monkeypatch.setenv("LOGALOG_DEBUG", "private-value-marker")
    with pytest.raises(ConfigurationError, match="LOGALOG_DEBUG") as error:
        log.debug("not-emitted")
    assert "private-value-marker" not in str(error.value)
    log.shutdown()
