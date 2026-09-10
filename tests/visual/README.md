# Image regression tests

Run `just test-images` for the focused checks. Full test runs also include them.

`test_visual.py` records the real Rich console after queued output is flushed.
It renders SVG to PNG with `resvg-py`. OpenImageIO compares the decoded pixels
with `console.png` at zero tolerance. Dimensions and channel counts must match.
Both delivery modes use the same reference. A negative test changes green text
to red and verifies that comparison fails and writes an RGB difference image.

The scene covers styled text, a table, nested sections, and warning wrapping.
Its terminal width, displayed time, source label, and fonts are fixed.
Functional tests separately check source attribution and logging behavior.
This image test does not check clocks, elapsed times, or actual terminal emulators.

## Rendering environment

Use the versions in `uv.lock`. The image tools are development dependencies.
The renderer loads only the bundled DejaVu Sans Mono fonts, not system fonts.
SVG web-font rules are removed from saved artifacts. Rendering needs no network.
The unmodified regular and bold fonts come from the
[DejaVu font project](https://dejavu-fonts.github.io/).
Their copyright and license notices are in `fonts/LICENSE.txt`.

The reference is verified on Linux. Other platforms need verification before
claiming that they produce identical pixels. Do not increase the tolerance to
hide an unexplained renderer or font change.

## Review a change

1. Run `just test-images`.
2. If a comparison fails, open the reference, actual PNG, and difference PNG.
   The failure message gives their paths. The actual SVG is beside the actual PNG.
3. Check whether the changed appearance is intended. Fix unintended changes.
4. For an intended change, replace `tests/visual/console.png` with the reviewed
   actual PNG from the normal scene, not the deliberate red-text test.
5. Run `just test-images` again, then run the full suite.
6. Commit the reference with the code that changes its appearance.

Tests never create or update the reference automatically. A missing or unreadable
reference fails. Generated output stays in pytest temporary directories.
