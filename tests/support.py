"""
Shared helpers for the SuperRTP test suites.

Runtime-dependent tests call `require(...)`: when the tool is missing they skip, unless
SUPERRTP_REQUIRE_RUNTIME=1 is set (as in CI), in which case they fail. That keeps local
runs usable on machines without the engines while CI cannot silently skip coverage.
"""

import os
import shutil
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

from png_utils import create_rgba_png, decode_png_rgb  # noqa: E402

RUNTIME_REQUIRED = os.environ.get("SUPERRTP_REQUIRE_RUNTIME") == "1"

# Canonical 2k-family geometry, written out independently of tools/transforms.py so the
# transform tests compare against a separate oracle.
CANONICAL_ROW = {"UP": 0, "RIGHT": 1, "DOWN": 2, "LEFT": 3}
CANONICAL_COL = {"STEP_LEFT": 0, "IDLE": 1, "STEP_RIGHT": 2}


def require(test, available: bool, what: str) -> None:
    if not available:
        if RUNTIME_REQUIRED:
            test.fail(f"{what} is required by SUPERRTP_REQUIRE_RUNTIME=1 but is not available")
        test.skipTest(f"{what} not available")


def have(executable: str, *fallbacks: str) -> bool:
    return bool(shutil.which(executable)) or any(os.access(os.path.expanduser(f), os.X_OK) for f in fallbacks)


def read_bytes(*parts) -> bytes:
    with open(os.path.join(REPO_ROOT, *parts), "rb") as f:
        return f.read()


def canonical_walking_rgba() -> bytes:
    return read_bytes("registry", "assets", "test_calibration_walking_character.rgba")


def crop(rgba: bytes, width: int, x: int, y: int, w: int = 24, h: int = 32) -> bytes:
    """Raw RGBA bytes of the w x h rectangle at (x, y) of an image `width` pixels wide."""
    return b"".join(rgba[((y + row) * width + x) * 4:((y + row) * width + x + w) * 4] for row in range(h))


def canonical_cell(rgba: bytes, char_idx: int, direction: str, phase: str) -> bytes:
    """One 24x32 cell of the canonical 288x256 sheet, located from the documented geometry."""
    x = (char_idx % 4) * 72 + CANONICAL_COL[phase] * 24
    y = (char_idx // 4) * 128 + CANONICAL_ROW[direction] * 32
    return crop(rgba, 288, x, y)


def rewrite_screenshot(path: str, change) -> None:
    """Rewrites a truecolor PNG in place; `change(x, y, rgb)` returns the new rgb."""
    w, h, rows = decode_png_rgb(path)
    out = bytearray()
    for y, row in enumerate(rows):
        for x, rgb in enumerate(row):
            out.extend(change(x, y, rgb))
            out.append(255)
    with open(path, "wb") as f:
        f.write(create_rgba_png(w, h, bytes(out)))
