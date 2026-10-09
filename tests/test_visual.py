"""Compare real console output with a reference PNG using OpenImageIO."""

import os
import re
from collections.abc import Callable
from functools import partial
from io import StringIO
from logging import LogRecord
from pathlib import Path

import OpenImageIO as oiio
import pytest
import resvg_py
from rich.console import Console
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from logalog import _backend
from logalog._logger import Logger

ASSETS = Path(__file__).parent / "visual"


def _render_scene(
    monkeypatch: pytest.MonkeyPatch,
    directory: Path,
    *,
    synchronous: bool,
    style: str = "green",
    width: int = 72,
    scene: Callable[[Logger], None] | None = None,
) -> Path:
    """Render one fixed-width scene through the library's real console sink."""
    console = Console(
        file=StringIO(),
        width=width,
        record=True,
        force_terminal=True,
        color_system="truecolor",
        markup=False,
        highlight=False,
    )
    original_emit = _backend._SnapshotHandler.emit

    def emit(handler: _backend._SnapshotHandler, record: LogRecord) -> None:
        record.pathname = "visual_example.py"
        record.lineno = 12
        original_emit(handler, record)

    with monkeypatch.context() as patch:
        for name in os.environ:
            if name.startswith("VISUAL_TEST_"):
                patch.delenv(name)
        patch.setenv("VISUAL_TEST_DEBUG", "1")
        patch.setenv("VISUAL_TEST_VERBOSE", "1")
        patch.setattr(_backend, "Console", lambda **kwargs: console)
        patch.setattr(
            _backend,
            "create_renderer",
            lambda: Console(
                stderr=True, markup=False, highlight=False, width=width, color_system="truecolor"
            ),
        )
        patch.setattr(_backend._SnapshotHandler, "emit", emit)
        # The console shows the event time. Fix the displayed time so images match.
        patch.setattr(
            _backend,
            "_SnapshotHandler",
            partial(_backend._SnapshotHandler, log_time_format=lambda _: Text("12:00:00")),
        )
        log = Logger(synchronous=synchronous, prefix="VISUAL_TEST")
        try:
            if scene is None:
                _basic_scene(log, style=style)
            else:
                scene(log)
            log.flush()
        finally:
            log.shutdown()

    directory.mkdir(parents=True, exist_ok=True)
    (directory / "actual.txt").write_text(console.export_text(clear=False), encoding="utf8")
    svg = console.export_svg(title="logalog", unique_id="visual-test")
    # Keep exported artifacts offline and use the bundled font for the title too.
    svg = re.sub(r"@font-face\s*\{[^}]*\}", "", svg)
    svg = svg.replace("font-family: arial;", "font-family: monospace;")
    # resvg uses only the bundled fonts; it does not load SVG web fonts.
    png = resvg_py.svg_to_bytes(
        svg_string=svg,
        skip_system_fonts=True,
        font_files=[
            str(ASSETS / "fonts" / name)
            for name in (
                "DejaVuSansMono.ttf",
                "DejaVuSansMono-Bold.ttf",
                "DejaVuSansMono-Oblique.ttf",
            )
        ],
        font_family="DejaVu Sans Mono",
        monospace_family="DejaVu Sans Mono",
        sans_serif_family="DejaVu Sans Mono",
    )
    (directory / "actual.svg").write_text(svg, encoding="utf8")
    actual = directory / "actual.png"
    actual.write_bytes(png)
    return actual


def _basic_scene(log: Logger, *, style: str = "green") -> None:
    """Keep the original reference scene unchanged."""
    with log.section("Build"):
        log.info(Text("Completed", style=style))
        table = Table("Task", "Status")
        table.add_row("Compile", "Complete")
        log.info(table)
        with log.section("Details"):
            log.warning("A long message checks wrapping at the fixed terminal width.")


def _levels(log: Logger) -> None:
    """Show every level, including independently enabled debug and verbose."""
    log.trace("Trace")
    log.debug("Debug")
    log.verbose("Verbose")
    log.info("Info")
    log.success("Success")
    log.warning("Warning")
    log.error("Error")
    log.critical("Critical")
    log.exception("No active exception")


def _wrapping(log: Logger) -> None:
    """Cover paragraphs, empty lines, literal markup, tabs, and long tokens."""
    log.info("First paragraph wraps at word boundaries without losing its final word: END.")
    log.info("First line\n\nThird line\nFourth line")
    log.info("")
    log.info("[red]literal[/red] {braces}")
    log.info("path/" + "abcdefghij" * 6 + "/END")
    log.info("tab\tstop")


def _indentation(log: Logger) -> None:
    """Show deep nesting, multiline text, siblings, and restored outer depth."""
    with log.section("Outer"):
        log.info("Outer body")
        with log.section("Middle"):
            with log.section("Inner"):
                log.info("First inner line\nSecond inner line")
            log.info("Back to middle")
        with log.section("Sibling"):
            log.info("Sibling body")
    log.info("Outside")


def _tables(log: Logger) -> None:
    """Show headers, alignment, wrapped cells, and an empty table."""
    table = Table("Task", "N", title="Tasks")
    table.columns[0].max_width = 10
    table.columns[1].justify = "right"
    table.add_row("Compile sources", "12")
    table.add_row("Two\nlines", "3")
    table.add_row("", "0")
    log.info(table)
    log.info(Table("Empty", "N"))


def _styles(log: Logger) -> None:
    """Show named and RGB colors, emphasis, and supported Unicode glyphs."""
    for color in ("red", "green", "blue", "yellow", "cyan", "magenta"):
        log.info(Text(color, style=color))
    log.info(Text("RGB", style="#4cb1ef on #302050"))
    for style in ("bold", "italic", "underline", "strike", "reverse"):
        log.info(Text(style, style=style))
    log.info(Text("café Ω → ✓", style="bold green"))
    log.info("Plain after styles")


def _code_and_commands(log: Logger) -> None:
    """Show code layout, command quoting, and redaction without execution."""
    log.info(Syntax("def add(a, b):\n    return a + b", "python", theme="monokai"))
    log.command(
        ["tool", "--name", "two words", "--token", "PRIVATE"], cwd="work", redact_indices=(4,)
    )
    log.info("After command")


SCENES = {
    "levels": _levels,
    "wrapping": _wrapping,
    "indentation": _indentation,
    "tables": _tables,
    "styles": _styles,
    "code-and-commands": _code_and_commands,
}


def _assert_image_matches(actual_path: Path, expected_path: Path) -> None:
    """Compare decoded pixels exactly and save an opaque difference image."""
    actual, expected = oiio.ImageBuf(str(actual_path)), oiio.ImageBuf(str(expected_path))
    assert actual.read(), actual.geterror()
    assert expected.read(), f"Cannot read reference {expected_path}: {expected.geterror()}"
    actual_spec, expected_spec = actual.spec(), expected.spec()
    assert (actual_spec.width, actual_spec.height, actual_spec.nchannels) == (
        expected_spec.width,
        expected_spec.height,
        expected_spec.nchannels,
    ), f"Image dimensions or channels differ: {actual_path} versus {expected_path}"
    result = oiio.ImageBufAlgo.compare(actual, expected, 0.0, 0.0)
    assert not actual.has_error, actual.geterror()
    assert not expected.has_error, expected.geterror()
    if result.nfail:
        difference = oiio.ImageBufAlgo.absdiff(actual, expected)
        # Equal alpha channels subtract to zero; omit alpha so the diff is visible.
        difference = oiio.ImageBufAlgo.channels(difference, (0, 1, 2))
        diff_path = actual_path.with_name("difference.png")
        assert difference.write(str(diff_path), oiio.UINT8), difference.geterror()
        pytest.fail(
            f"{result.nfail} pixels differ (max error {result.maxerror}). "
            f"Expected: {expected_path}; actual: {actual_path}; difference: {diff_path}"
        )
    assert not result.error, f"Image comparison failed: {actual_path} versus {expected_path}"


@pytest.mark.parametrize("synchronous", [False, True], ids=["queued", "synchronous"])
def test_console_image(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    synchronous: bool,
) -> None:
    """Match one reference image in both logging delivery modes."""
    actual = _render_scene(monkeypatch, tmp_path, synchronous=synchronous)
    _assert_image_matches(actual, ASSETS / "console.png")


@pytest.mark.parametrize("synchronous", [False, True], ids=["queued", "synchronous"])
@pytest.mark.parametrize("width", [72, 80, 120], ids=["narrow", "standard", "wide"])
@pytest.mark.parametrize("scene", SCENES)
def test_visual_scenes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    synchronous: bool,
    width: int,
    scene: str,
) -> None:
    """Match reviewed layouts across widths and both delivery modes."""
    actual = _render_scene(
        monkeypatch,
        tmp_path,
        synchronous=synchronous,
        width=width,
        scene=SCENES[scene],
    )
    _assert_image_matches(actual, ASSETS / f"{scene}-{width}.png")


@pytest.mark.parametrize("synchronous", [False, True], ids=["queued", "synchronous"])
def test_narrow_table_keeps_borders(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    synchronous: bool,
) -> None:
    """Keep narrow table borders intact in the full-width snapshot row."""
    _render_scene(monkeypatch, tmp_path, synchronous=synchronous, width=48, scene=_tables)
    lines = (tmp_path / "actual.txt").read_text().splitlines()
    top_borders = [line for line in lines if "┏" in line]
    assert len(top_borders) == 2
    assert all("┓" in line for line in top_borders)
    _assert_image_matches(tmp_path / "actual.png", ASSETS / "tables-48.png")


@pytest.mark.parametrize("synchronous", [False, True], ids=["queued", "synchronous"])
def test_nested_narrow_table_keeps_borders(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    synchronous: bool,
) -> None:
    """Reserve section indentation before rendering a full-width table."""

    def scene(log: Logger) -> None:
        with log.section("A"), log.section("B"), log.section("C"):
            table = Table("Task", "N", expand=True)
            table.add_row("Compile", "12")
            log.info(table)

    _render_scene(monkeypatch, tmp_path, synchronous=synchronous, width=48, scene=scene)
    lines = (tmp_path / "actual.txt").read_text().splitlines()
    border = next(line for line in lines if "┏" in line)
    assert border.startswith("    ┏")
    assert "┓" in border
    _assert_image_matches(tmp_path / "actual.png", ASSETS / "tables-nested-48.png")


def test_wrong_width_is_detected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Reject a changed canvas width before attempting a pixel comparison."""
    actual = _render_scene(monkeypatch, tmp_path, synchronous=False, width=80)
    with pytest.raises(AssertionError, match="dimensions or channels differ"):
        _assert_image_matches(actual, ASSETS / "console.png")


def test_color_regression_is_detected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Reject a real style change and produce a readable difference image."""
    actual = _render_scene(monkeypatch, tmp_path, synchronous=False, style="red")
    with pytest.raises(pytest.fail.Exception, match="pixels differ"):
        _assert_image_matches(actual, ASSETS / "console.png")
    difference = oiio.ImageBuf(str(tmp_path / "difference.png"))
    assert difference.read(), difference.geterror()
    assert difference.spec().nchannels == 3
