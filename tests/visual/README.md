# Image regression tests

Run `just test-images` for the focused checks. Full test runs also include them.

`test_visual.py` records the real Rich console after queued output is flushed.
It renders SVG to PNG with `resvg-py`. OpenImageIO compares the decoded pixels
with reviewed reference PNGs at zero tolerance. Dimensions and channel counts
must match. Both delivery modes use the same reference for each scene and width.
Negative tests detect a changed color and an incorrect canvas width.

## Coverage

The main scenes run at 72, 80, and 120 columns in both delivery modes.
The original mixed scene remains as a separate reference.

| Scene | Cases |
| --- | --- |
| Levels | Trace, debug, verbose, info, success, warning, error, critical, and exception without an active traceback |
| Wrapping | Paragraphs, explicit and empty lines, an empty message, literal markup/braces, long tokens, and tabs |
| Indentation | Three nested sections, multiline messages, siblings, and restored outer depth |
| Tables | Titles, headers, right-aligned numbers, wrapped/multiline/empty cells, and an empty table |
| Styles | Named and RGB colors, backgrounds, bold, italic, underline, strike, reverse, Unicode, and plain text after styles |
| Code and commands | Syntax highlighting, code indentation, command quoting, redaction, working directory, and wrapped arguments |

Displayed time, source labels, and fonts are fixed. Each case gets a fresh console.
Functional tests separately check source attribution, filtering, and logging behavior.
These images do not check clocks, elapsed times, active tracebacks, terminal-height
limits, dynamic resizing, terminal emulators, or all terminal color capabilities.

## Narrow tables

Rich snapshots appear below their metadata header, outside its narrow message
column. The producer reserves section indentation before rendering each object.
At 48 columns, tests check both plain and deeply nested tables in each delivery
mode. They verify intact borders and compare approved PNG references.
These cases are normal passing tests, not expected failures.

## Rendering environment

Use the versions in `uv.lock`. The image tools are development dependencies.
The renderer loads only the bundled DejaVu Sans Mono fonts, not system fonts.
SVG web-font rules are removed from saved artifacts. Rendering needs no network.
The unmodified regular, bold, and oblique fonts come from the
[DejaVu font project](https://dejavu-fonts.github.io/).
Their copyright and license notices are in `fonts/LICENSE.txt`.

The reference is verified on Linux. Other platforms need verification before
claiming that they produce identical pixels. Do not increase the tolerance to
hide an unexplained renderer or font change.

## Review a change

1. Run `just test-images`.
2. If a comparison fails, open the reference, actual PNG, and difference PNG.
   The failure message gives their paths. The actual SVG and text capture are
   beside the actual PNG.
3. Check whether the changed appearance is intended. Fix unintended changes.
4. For an intended change, replace the matching reference in `tests/visual/`
   with the reviewed actual PNG. Names include the scene and column width.
   Keep `console.png` for the original scene. Do not copy a deliberate failure.
5. Run `just test-images` again, then run the full suite.
6. Commit the reference with the code that changes its appearance.

Tests never create or update the reference automatically. A missing or unreadable
reference fails. Generated output stays in pytest temporary directories.
