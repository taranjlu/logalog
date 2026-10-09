"""Verify explicit isolated configuration loading."""

import json
import multiprocessing
import os
import subprocess
import sys
from pathlib import Path

import pytest
from beartype.roar import BeartypeCallHintParamViolation

from logalog import Configuration, ConfigurationError, load_configuration
from logalog._logger import Logger


def _write(path: Path, text: str) -> Path:
    """Write and return one test configuration path."""
    path.write_text(text)
    return path


def _call_as(log: Logger, module: str, method: str, message: str) -> None:
    """Make a call with a selected caller module."""
    exec(  # noqa: S102 -- A selected namespace tests stored module controls.
        compile(f"log.{method}({message!r})", "configured.py", "exec"),
        {"__name__": module, "log": log},
    )


def test_formats_merge_in_order_and_resolve_file_path(tmp_path: Path) -> None:
    """Load pyproject, JSON, YAML, and TOML with later recursive overrides."""
    project = _write(
        tmp_path / "pyproject.toml",
        """
[project]
name = "ignored"
[tool.logalog]
prefix = "PROJECT"
debug = true
[tool.logalog.modules.app]
verbose = true
debug = false
""",
    )
    json_path = tmp_path / "settings.json"
    json_path.write_text(json.dumps({"prefix": "JSON", "modules": {"app": {"debug": True}}}))
    yaml_path = _write(
        tmp_path / "settings.yaml",
        """
silent: false
modules:
  app:
    verbose: false
""",
    )
    toml_path = _write(
        tmp_path / "last.toml",
        """
synchronous = true
files = [{path = "logs/events.log", rotation = 100, retention = 2}]
""",
    )

    configuration = load_configuration(project, json_path, yaml_path, toml_path)

    assert configuration.synchronous is True
    assert configuration.prefix == "JSON"
    assert configuration.debug is True
    assert dict(configuration.modules) == {"app": (False, True, None)}
    assert configuration.files[0].path == tmp_path / "logs/events.log"
    assert configuration.files[0].rotation == 100


def test_stored_controls_are_defaults_for_live_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Keep file defaults below live global and module environment values."""
    path = _write(
        tmp_path / "controls.yaml",
        """
synchronous: true
debug: true
silent: false
modules:
  app:
    debug: false
    verbose: true
  muted:
    silent: true
  muted.child:
    silent: false
""",
    )
    log = Logger()
    log.configure(configuration=load_configuration(path))
    log.debug("global-default")
    _call_as(log, "app.worker", "debug", "module-hidden")
    _call_as(log, "app.worker", "verbose", "module-default")
    _call_as(log, "muted.child", "info", "stored-silent")
    monkeypatch.setenv("LOGALOG_MODULE__617070_DEBUG", "1")
    _call_as(log, "app.worker", "debug", "live-module")
    monkeypatch.setenv("LOGALOG_SILENT", "1")
    log.error("live-hidden")
    monkeypatch.delenv("LOGALOG_SILENT")
    log.error("restored")
    log.shutdown()

    output = capsys.readouterr().err
    assert "global-default" in output
    assert "module-hidden" not in output
    assert "module-default" in output
    assert "stored-silent" not in output
    assert "live-module" in output
    assert "live-hidden" not in output
    assert "restored" in output


def test_live_false_overrides_stored_global_silence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Let a live value replace its stored value at the same scope."""
    path = _write(tmp_path / "silent.json", '{"synchronous": true, "silent": true}')
    log = Logger()
    log.configure(configuration=load_configuration(path))
    log.info("stored-hidden")
    monkeypatch.setenv("LOGALOG_SILENT", "false")
    log.info("live-visible")
    log.shutdown()
    output = capsys.readouterr().err
    assert "stored-hidden" not in output
    assert "live-visible" in output


@pytest.mark.parametrize(
    ("name", "text", "match"),
    [
        ("settings.ini", "debug=true", "suffixes"),
        ("settings.xml", "<settings/>", "suffixes"),
        ("settings.yaml", "base: &base {}\n<<: *base", "constructor"),
        ("settings.toml", "debug =", "settings.toml"),
        ("settings.json", "{", "settings.json"),
        ("settings.yaml", "debug: [", "settings.yaml"),
        ("settings.yaml", "debug: true\ndebug: false\n", "duplicate key"),
        ("settings.json", '{"debug": true, "debug": false}', "Duplicate key"),
        ("settings.yaml", "!!python/object:os.system {}", "constructor"),
        ("settings.yaml", "? [a, b]\n: value", "unhashable"),
        ("settings.yaml", "- item", "document must be a mapping"),
        ("settings.yaml", "unknown: true", "unknown configuration"),
        ("settings.yaml", "debug: 1", "debug must be a Boolean"),
        ("settings.yaml", "debug: on", "debug must be a Boolean"),
        ("settings.yaml", "synchronous: 0", "synchronous must be a Boolean"),
        ("settings.yaml", "prefix: 2", "invalid prefix"),
        ("settings.yaml", "modules: []", "modules must be a mapping"),
        ("settings.yaml", "modules: {bad..name: {}}", "nonempty dot-separated parts"),
        ("settings.yaml", "modules: {app: []}", "modules.app must be a mapping"),
        ("settings.yaml", "modules: {app: {other: true}}", "unknown modules.app"),
        ("settings.yaml", "modules: {app: {debug: 1}}", "must be a Boolean"),
        ("settings.yaml", "files: {}", "files must be a list"),
        ("settings.yaml", "files: [[]]", "files\\[0\\] must be a mapping"),
        ("settings.yaml", "files: [{kind: text}]", "path must be a string"),
        ("settings.yaml", "files: [{path: x, extra: 1}]", "unknown files"),
        ("settings.yaml", "files: [{path: x, delay: 1}]", "invalid files"),
        ("settings.yaml", "files: [{path: x, rotation: true}]", "invalid files"),
        ("settings.yaml", "files: [{path: x, buffering: false}]", "invalid files"),
    ],
)
def test_malformed_configuration_has_source_and_clear_path(
    tmp_path: Path, name: str, text: str, match: str
) -> None:
    """Reject unsafe, malformed, unknown, and incorrectly typed values."""
    path = _write(tmp_path / name, text)
    with pytest.raises(ConfigurationError, match=match) as error:
        load_configuration(path)
    assert str(path) in str(error.value)


def test_missing_file_and_bad_utf8_are_clear(tmp_path: Path) -> None:
    """Wrap file and text decoding failures with the source path."""
    missing = tmp_path / "missing.toml"
    with pytest.raises(ConfigurationError, match=r"missing\.toml"):
        load_configuration(missing)
    invalid = tmp_path / "invalid.json"
    invalid.write_bytes(b"\xff")
    with pytest.raises(ConfigurationError, match=r"invalid\.json"):
        load_configuration(invalid)


def test_configuration_failure_does_not_mutate_logger(tmp_path: Path) -> None:
    """Keep the logger configurable after a source fails validation."""
    log = Logger()
    invalid = _write(tmp_path / "invalid.toml", 'prefix = "bad"')
    with pytest.raises(ConfigurationError, match="invalid prefix"):
        log.configure(configuration=load_configuration(invalid))
    assert log._backend is None
    log.configure(synchronous=True)
    log.shutdown()


def test_explicit_api_values_override_loaded_delivery(tmp_path: Path) -> None:
    """Give explicit API delivery values priority over stored values."""
    path = _write(tmp_path / "settings.json", '{"synchronous": false, "prefix": "FILE"}')
    log = Logger()
    log.configure(configuration=load_configuration(path), synchronous=True, prefix="API")
    assert log._synchronous is True
    assert log._prefix == "API"
    log.shutdown()


def test_loaded_file_collisions_fail_before_initialization(tmp_path: Path) -> None:
    """Apply existing one-writer validation to loaded destinations."""
    path = _write(
        tmp_path / "settings.yaml",
        "files: [{path: events.log}, {path: ./events.log, kind: json}]",
    )
    log = Logger()
    with pytest.raises(ValueError, match="unique"):
        log.configure(configuration=load_configuration(path))
    assert log._backend is None
    log.shutdown()


def test_import_and_loading_do_not_read_cli_or_unrelated_environment(tmp_path: Path) -> None:
    """Do not search, parse application arguments, or replace environment paths."""
    config = _write(tmp_path / "explicit.json", '{"debug": true}')
    script = """
import os, sys
before = dict(os.environ)
from logalog import load_configuration
assert load_configuration(sys.argv[1]).debug is True
assert dict(os.environ) == before
from configurator import Config
unrelated = Config({"files": ["first"]})
unrelated.merge({"files": ["second"]})
assert unrelated.data["files"] == ["first", "second"]
assert sys.argv[2:] == ['--application-flag']
"""
    environment = os.environ.copy()
    environment["OMNICONF_JSON_FILENAME"] = str(tmp_path / "missing.json")
    result = subprocess.run(  # noqa: S603 -- Fixed isolated test script.
        [sys.executable, "-I", "-c", script, str(config), "--application-flag"],
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert result.stderr == ""


@pytest.mark.parametrize(
    ("suffix", "text"),
    [
        ("yaml", "!!map [1]"),
        ("json", '{"files": [{"path": ""}]}'),
        ("json", '{"prefix": "lower-case"}'),
    ],
)
def test_invalid_structure_has_source_error(tmp_path: Path, suffix: str, text: str) -> None:
    """Reject malformed mappings, empty destinations, and invalid prefixes."""
    path = _write(tmp_path / f"invalid.{suffix}", text)
    with pytest.raises(ConfigurationError, match=str(path)):
        load_configuration(path)


def test_earlier_invalid_source_is_not_hidden_or_misattributed(tmp_path: Path) -> None:
    """Report the actual source even when a later file replaces its value."""
    bad = _write(tmp_path / "bad.json", '{"debug": "not-a-boolean"}')
    good = _write(tmp_path / "good.json", '{"debug": false}')
    with pytest.raises(ConfigurationError, match=f"{bad}: debug"):
        load_configuration(bad, good)


def test_relative_destinations_survive_working_directory_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Anchor destination paths when configuration loads, not when logging starts."""
    root = tmp_path / "source"
    root.mkdir()
    _write(root / "settings.json", '{"files": [{"path": "events.log"}]}')
    monkeypatch.chdir(root)
    config = load_configuration("settings.json")
    monkeypatch.chdir(tmp_path)
    log = Logger()
    log.configure(configuration=config, synchronous=True)
    log.info("source-relative-marker")
    log.shutdown()
    assert "source-relative-marker" in (root / "events.log").read_text()
    assert not (tmp_path / "events.log").exists()


@pytest.mark.parametrize("name", ["", "bad..name"])
def test_programmatic_modules_require_valid_names(name: str) -> None:
    """Reject invalid module scopes before any logger can use them."""
    with pytest.raises(ConfigurationError, match="nonempty"):
        Configuration(modules=((name, (None, None, None)),))


def test_programmatic_modules_reject_duplicate_names() -> None:
    """Reject ambiguous repeated module defaults."""
    with pytest.raises(ConfigurationError, match="unique"):
        Configuration(modules=(("app", (None, True, None)), ("app", (True, None, None))))


def test_programmatic_modules_check_every_entry() -> None:
    """Check all module controls and every public source argument."""
    valid = tuple((f"module{index}", (None, True, None)) for index in range(10))
    with pytest.raises(BeartypeCallHintParamViolation):
        Configuration(modules=(*valid, ("bad", (None, "yes", None))))  # ty: ignore[invalid-argument-type]
    with pytest.raises(BeartypeCallHintParamViolation):
        load_configuration(42)  # ty: ignore[invalid-argument-type]


@pytest.mark.parametrize("method", multiprocessing.get_all_start_methods())
def test_workers_keep_stored_defaults_and_live_overrides(tmp_path: Path, method: str) -> None:
    """Transfer global and module defaults without freezing worker environment values."""
    config = _write(
        tmp_path / "worker.json",
        '{"debug": true, "modules": {"app.worker": {"verbose": true}}}',
    )
    script = r"""
import multiprocessing as mp
import os
import sys
from types import FunctionType
from logalog import LOG, initialize_worker, load_configuration

def messages():
    LOG.debug("stored-global-marker")
    LOG.verbose("stored-module-marker")

emit = FunctionType(messages.__code__, {"__name__": "app.worker", "LOG": LOG})

def work(owner):
    initialize_worker(owner)
    emit()
    os.environ["LOGALOG_DEBUG"] = "0"
    LOG.debug("hidden-worker-marker")
    LOG.shutdown()

if __name__ == "__main__":
    mp.set_start_method(sys.argv[1])
    LOG.configure(configuration=load_configuration(sys.argv[2]))
    LOG.initialize()
    worker = mp.Process(target=work, args=(LOG,))
    worker.start()
    worker.join(15)
    if worker.is_alive():
        worker.terminate()
        worker.join(5)
        raise RuntimeError("Worker did not exit")
    assert worker.exitcode == 0
    LOG.info("owner-still-active-marker")
    LOG.shutdown()
"""
    path = _write(tmp_path / "worker.py", script)
    result = subprocess.run(  # noqa: S603 -- Fixed isolated test script.
        [sys.executable, str(path), method, str(config)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert not result.stdout
    assert "hidden-worker-marker" not in result.stderr
    for marker in ("stored-global-marker", "stored-module-marker", "owner-still-active-marker"):
        assert result.stderr.count(marker) == 1


@pytest.mark.parametrize("clear_files", [False, True])
def test_later_sources_can_keep_or_remove_earlier_destinations(
    tmp_path: Path, clear_files: bool
) -> None:
    """Keep original path anchors unless a later list replaces the destinations."""
    early = tmp_path / "early"
    late = tmp_path / "late"
    early.mkdir()
    late.mkdir()
    first = _write(early / "settings.json", '{"files": [{"path": "events.log"}]}')
    second = _write(
        late / "settings.json",
        '{"files": []}' if clear_files else '{"prefix": "LATER"}',
    )
    config = load_configuration(first, second)
    if clear_files:
        assert config.files == ()
    else:
        assert len(config.files) == 1
        assert config.files[0].path == early / "events.log"
        assert config.prefix == "LATER"
