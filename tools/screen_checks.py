#!/usr/bin/env python3
"""
Pixel assertions shared by the target validator and the runtime verifiers.

Screenshots are decoded with png_utils.decode_png_rgb into rows of (r, g, b) tuples;
sheets are raw RGBA bytes. Coordinates are (x, y) with the origin at the top left.
"""

# Calibration arrow geometry inside one 24x32 cell (tools/generate_calibration_charset.py):
# direction -> (tip, notch, tip description, notch description). The tip is an opaque
# outline pixel; the notch opposite it is transparent.
ARROW_PROBES = {
    "DOWN": ((11, 21), (11, 6), "center-bottom", "center-top"),
    "LEFT": ((4, 13), (19, 13), "center-left", "center-right"),
    "RIGHT": ((19, 13), (4, 13), "center-right", "center-left"),
    "UP": ((11, 5), (11, 21), "center-top", "center-bottom"),
}

# Foot marker pixel (x, y) inside a cell for each stepping phase.
STEP_FOOT_PROBES = {"STEP_LEFT": (8, 27), "STEP_RIGHT": (16, 27)}

CELL_W, CELL_H = 24, 32


def rgb_at(frame: bytes, width: int, x: int, y: int) -> tuple:
    """Pixel (x, y) of a raw RGB24 frame, as used by the cheap video-sample classifiers."""
    o = (y * width + x) * 3
    return tuple(frame[o:o + 3])


def check_markers(pixels, markers) -> None:
    """`markers` is [(label, (x, y), expected_rgb)]; raises '<label> mismatch' on the first difference."""
    for label, (x, y), expected in markers:
        actual = pixels[y][x]
        if actual != expected:
            raise ValueError(f"{label} mismatch: expected {expected}, got {actual}")


def check_screen_arrows(pixels, origin_x, origin_y, rows, column, tip_color, notch_color, label="") -> None:
    """
    On a 1:1 screenshot, checks every row's arrow in `column` of a sheet drawn at
    (origin_x, origin_y): the tip shows `tip_color`, the transparent notch shows `notch_color`.
    """
    for row, direction in enumerate(rows):
        (tx, ty), (nx, ny), _, _ = ARROW_PROBES[direction]
        cx = origin_x + column * CELL_W
        cy = origin_y + row * CELL_H
        tip = pixels[cy + ty][cx + tx]
        notch = pixels[cy + ny][cx + nx]
        if tip != tip_color:
            raise ValueError(f"{label}Row {row} {direction} Col {column} arrow tip mismatch: expected {tip_color}, got {tip}")
        if notch != notch_color:
            raise ValueError(f"{label}Row {row} {direction} Col {column} notch transparency mismatch: expected {notch_color}, got {notch}")


def check_composite(pixels, sheet_rgba: bytes, sheet_w: int, sheet_h: int, origin_x: int, origin_y: int,
                    background, scale: int = 1, tolerance: int = 0, label: str = "sheet") -> None:
    """
    Requires a sheet drawn at (origin_x, origin_y), optionally scaled by an integer factor,
    to match its source: opaque pixels show the sheet color (within `tolerance` per channel)
    and fully transparent pixels show `background`. Partial alpha is not checked.
    """
    for sy in range(sheet_h):
        for sx in range(sheet_w):
            o = (sy * sheet_w + sx) * 4
            alpha = sheet_rgba[o + 3]
            screen = pixels[origin_y + sy * scale][origin_x + sx * scale]
            if alpha == 255:
                expected = tuple(sheet_rgba[o:o + 3])
                if max(abs(a - b) for a, b in zip(screen, expected)) > tolerance:
                    raise ValueError(f"Opaque pixel mismatch in {label} at ({sx}, {sy}): expected {expected}, got {screen}")
            elif alpha == 0 and screen != background:
                raise ValueError(f"Transparent pixel in {label} at ({sx}, {sy}) should show background {background}, got {screen}")
