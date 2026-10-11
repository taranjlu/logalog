# /// script
# requires-python = ">=3.11,<3.15"
# dependencies = ["openimageio==3.1.17.0"]
# ///
"""Compare two PNG images exactly with OpenImageIO.

The visual tests run this script with ``uv run --script`` in a separate environment.
OpenImageIO does not have a wheel for every Python version that logalog supports.
The script exits with 0 if the images match and with 1 if they do not match.
"""

import sys
from pathlib import Path

import OpenImageIO as oiio  # ty: ignore[unresolved-import]


def compare(actual_path: Path, expected_path: Path) -> str | None:
    """Compare decoded pixels exactly and save an opaque difference image.

    Parameters
    ----------
    actual_path : Path
        The rendered image.
    expected_path : Path
        The reviewed reference image.

    Returns
    -------
    str or None
        A failure message, or ``None`` if the images match.
    """
    actual, expected = oiio.ImageBuf(str(actual_path)), oiio.ImageBuf(str(expected_path))
    if not actual.read():
        return f"Cannot read {actual_path}: {actual.geterror()}"
    if not expected.read():
        return f"Cannot read reference {expected_path}: {expected.geterror()}"
    actual_spec, expected_spec = actual.spec(), expected.spec()
    if (actual_spec.width, actual_spec.height, actual_spec.nchannels) != (
        expected_spec.width,
        expected_spec.height,
        expected_spec.nchannels,
    ):
        return f"Image dimensions or channels differ: {actual_path} versus {expected_path}"
    result = oiio.ImageBufAlgo.compare(actual, expected, 0.0, 0.0)
    if actual.has_error or expected.has_error:
        return f"Image comparison failed: {actual.geterror()} {expected.geterror()}"
    if result.nfail:
        difference = oiio.ImageBufAlgo.absdiff(actual, expected)
        # Equal alpha channels subtract to zero; omit alpha so the diff is visible.
        difference = oiio.ImageBufAlgo.channels(difference, (0, 1, 2))
        diff_path = actual_path.with_name("difference.png")
        if not difference.write(str(diff_path), oiio.UINT8):
            return f"Cannot write {diff_path}: {difference.geterror()}"
        return (
            f"{result.nfail} pixels differ (max error {result.maxerror}). "
            f"Expected: {expected_path}; actual: {actual_path}; difference: {diff_path}"
        )
    if result.error:
        return f"Image comparison failed: {actual_path} versus {expected_path}"
    return None


if __name__ == "__main__":
    message = compare(Path(sys.argv[1]), Path(sys.argv[2]))
    if message is not None:
        print(message)
        sys.exit(1)
