"""Compare real console output with a reference PNG using OpenImageIO."""

import os
import re
from functools import partial
from io import StringIO
from logging import LogRecord
from pathlib import Path

import OpenImageIO as oiio
import pytest
import resvg_py
from rich.console import Console
from rich.table import Table
from rich.text import Text

from malideiter import _backend, _logger
from malideiter._logger import Logger

ASSETS = Path(__file__).parent / "visual"


def _render_scene(
    monkeypatch: pytest.MonkeyPatch,
    directory: Path,
    *,
    synchronous: bool,
    style: str = "green",
) -> Path:
    """Render one fixed-width scene through the library's real console sink."""
    console = Console(
        file=StringIO(),
        width=72,
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
        patch.setattr(_backend, "Console", lambda **kwargs: console)
        patch.setattr(_logger, "Console", partial(Console, width=72, color_system="truecolor"))
        patch.setattr(_backend._SnapshotHandler, "emit", emit)
        # Loguru creates a fresh standard logging record. Fix displayed time here,
        # rather than changing a clock that the adapter does not use.
        patch.setattr(
            _backend,
            "_SnapshotHandler",
            partial(_backend._SnapshotHandler, log_time_format=lambda _: Text("12:00:00")),
        )
        log = Logger(synchronous=synchronous, prefix="VISUAL_TEST")
        try:
            with log.section("Build"):
                log.info(Text("Completed", style=style))
                table = Table("Task", "Status")
                table.add_row("Compile", "Complete")
                log.info(table)
                with log.section("Details"):
                    log.warning("A long message checks wrapping at the fixed terminal width.")
            log.flush()
        finally:
            log.shutdown()

    svg = console.export_svg(title="malideiter", unique_id="visual-test")
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
            )
        ],
        font_family="DejaVu Sans Mono",
        monospace_family="DejaVu Sans Mono",
        sans_serif_family="DejaVu Sans Mono",
    )
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "actual.svg").write_text(svg, encoding="utf8")
    actual = directory / "actual.png"
    actual.write_bytes(png)
    return actual


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


def test_color_regression_is_detected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Reject a real style change and produce a readable difference image."""
    actual = _render_scene(monkeypatch, tmp_path, synchronous=False, style="red")
    with pytest.raises(pytest.fail.Exception, match="pixels differ"):
        _assert_image_matches(actual, ASSETS / "console.png")
    difference = oiio.ImageBuf(str(tmp_path / "difference.png"))
    assert difference.read(), difference.geterror()
    assert difference.spec().nchannels == 3
