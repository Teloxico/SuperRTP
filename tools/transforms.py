#!/usr/bin/env python3
"""
Pure pixel transforms from canonical SuperRTP sources to engine-specific images.

Nothing in this module touches the filesystem. Each function takes bytes and returns
bytes, which keeps the transforms deterministic and directly testable.

Canonical walking-character source (see docs/engine-facts.md for the engine sources):
  - 288x256 RGBA, 8 characters in a 4x2 grid, 72x128 px per character
  - each character: 3 columns x 4 rows of 24x32 cells
  - rows in RPG Maker 2000/2003 order:   UP, RIGHT, DOWN, LEFT
  - columns:                             STEP_LEFT, IDLE, STEP_RIGHT

Target sheets are described by `SheetLayout` values and packed by one generic function,
so adding an engine means declaring a layout, not writing another copy loop.
"""

from dataclasses import dataclass

from png_utils import create_indexed_png, create_rgba_png

FRAME_W = 24
FRAME_H = 32
CANONICAL_SHEET_W = 288
CANONICAL_SHEET_H = 256
CANONICAL_CHARACTERS = 8

CANONICAL_ROWS = ("UP", "RIGHT", "DOWN", "LEFT")
CANONICAL_COLUMNS = ("STEP_LEFT", "IDLE", "STEP_RIGHT")


@dataclass(frozen=True)
class SheetLayout:
    """Physical arrangement of semantic frames in a target character sheet."""
    name: str
    rows: tuple              # direction per row, top to bottom
    columns: tuple           # animation phase per column, left to right
    characters_across: int = 1
    characters_down: int = 1

    @property
    def character_count(self) -> int:
        return self.characters_across * self.characters_down

    def size(self, frame_w: int = FRAME_W, frame_h: int = FRAME_H):
        return (self.characters_across * len(self.columns) * frame_w,
                self.characters_down * len(self.rows) * frame_h)


# RPG Maker XP / RGSS1: 4x4 cells. Column 3 repeats IDLE to fill XP's 4-pattern cycle.
# (docs/engine-facts.md records an open question about which column RGSS1 shows at rest.)
RMXP_LAYOUT = SheetLayout("rmxp_4x4", ("DOWN", "LEFT", "RIGHT", "UP"), ("STEP_LEFT", "IDLE", "STEP_RIGHT", "IDLE"))

# RPG Maker VX / VX Ace: standard 8-character sheet, 3 patterns x 4 directions each.
VX_FAMILY_LAYOUT = SheetLayout("vx_standard_8", ("DOWN", "LEFT", "RIGHT", "UP"), ("STEP_LEFT", "IDLE", "STEP_RIGHT"), 4, 2)

# WOLF RPG Editor 3: one 3-pattern / 4-direction CharaChip.
WOLF_LAYOUT = SheetLayout("wolf_p3_d4", ("DOWN", "LEFT", "RIGHT", "UP"), ("STEP_LEFT", "IDLE", "STEP_RIGHT"))


# ---------------------------------------------------------------------------
# Canonical sheet -> semantic frames
# ---------------------------------------------------------------------------

def extract_walking_frames(
    source_rgba_bytes: bytes,
    char_idx: int = 0,
    frame_w: int = FRAME_W,
    frame_h: int = FRAME_H,
    sheet_w: int = CANONICAL_SHEET_W,
    sheet_h: int = CANONICAL_SHEET_H,
) -> dict:
    """
    Extracts one character's frames from the canonical sheet.

    Returns frames[direction][phase] -> bytes of frame_w * frame_h RGBA pixels.
    """
    expected_len = sheet_w * sheet_h * 4
    if len(source_rgba_bytes) != expected_len:
        raise ValueError(f"Input RGBA buffer size mismatch: expected {expected_len}, got {len(source_rgba_bytes)}")
    if not (0 <= char_idx < CANONICAL_CHARACTERS):
        raise ValueError(f"Character index out of range (0..7): {char_idx}")

    char_base_x = (char_idx % 4) * (len(CANONICAL_COLUMNS) * frame_w)
    char_base_y = (char_idx // 4) * (len(CANONICAL_ROWS) * frame_h)
    row_bytes = frame_w * 4

    frames = {}
    for row_idx, direction in enumerate(CANONICAL_ROWS):
        frames[direction] = {}
        for col_idx, phase in enumerate(CANONICAL_COLUMNS):
            src_x = char_base_x + col_idx * frame_w
            src_y = char_base_y + row_idx * frame_h
            frame = bytearray()
            for py in range(frame_h):
                start = ((src_y + py) * sheet_w + src_x) * 4
                frame += source_rgba_bytes[start:start + row_bytes]
            frames[direction][phase] = bytes(frame)
    return frames


# ---------------------------------------------------------------------------
# Semantic frames -> target sheet
# ---------------------------------------------------------------------------

def pack_sheet_rgba(characters, layout: SheetLayout, frame_w: int = FRAME_W, frame_h: int = FRAME_H) -> bytes:
    """
    Arranges semantic frames into raw RGBA according to `layout`.

    `characters` is a sequence of frames[direction][phase] dicts, one per character slot,
    filled left to right, then top to bottom.
    """
    if not isinstance(characters, (list, tuple)) or len(characters) != layout.character_count:
        count = len(characters) if hasattr(characters, "__len__") else type(characters).__name__
        raise ValueError(f"Layout '{layout.name}' expects exactly {layout.character_count} semantic character(s), got {count}")

    width, height = layout.size(frame_w, frame_h)
    out = bytearray(width * height * 4)
    frame_len = frame_w * frame_h * 4
    row_bytes = frame_w * 4
    block_w = len(layout.columns) * frame_w
    block_h = len(layout.rows) * frame_h

    for char_idx, frames in enumerate(characters):
        base_x = (char_idx % layout.characters_across) * block_w
        base_y = (char_idx // layout.characters_across) * block_h
        for row_idx, direction in enumerate(layout.rows):
            if direction not in frames:
                raise KeyError(f"Missing required direction '{direction}' for character {char_idx}")
            for col_idx, phase in enumerate(layout.columns):
                if phase not in frames[direction]:
                    raise KeyError(f"Missing required phase '{phase}' for direction '{direction}' in character {char_idx}")
                frame = frames[direction][phase]
                if len(frame) != frame_len:
                    raise ValueError(f"Frame length mismatch for char {char_idx}/{direction}/{phase}: expected {frame_len}, got {len(frame)}")
                dst_x = base_x + col_idx * frame_w
                dst_y = base_y + row_idx * frame_h
                for py in range(frame_h):
                    dst = ((dst_y + py) * width + dst_x) * 4
                    out[dst:dst + row_bytes] = frame[py * row_bytes:(py + 1) * row_bytes]
    return bytes(out)


def pack_sheet_png(characters, layout: SheetLayout, frame_w: int = FRAME_W, frame_h: int = FRAME_H) -> bytes:
    """`pack_sheet_rgba` encoded as a deterministic truecolor RGBA PNG."""
    width, height = layout.size(frame_w, frame_h)
    return create_rgba_png(width, height, pack_sheet_rgba(characters, layout, frame_w, frame_h))


def pack_rmxp_character(semantic_frames: dict, frame_w: int = FRAME_W, frame_h: int = FRAME_H) -> bytes:
    """RPG Maker XP / RGSS1 96x128 sheet (see RMXP_LAYOUT)."""
    return pack_sheet_png([semantic_frames], RMXP_LAYOUT, frame_w, frame_h)


def pack_vx_family_standard_character_sheet(semantic_characters, frame_w: int = FRAME_W, frame_h: int = FRAME_H) -> bytes:
    """RPG Maker VX / VX Ace 288x256 standard 8-character sheet (see VX_FAMILY_LAYOUT)."""
    return pack_sheet_png(semantic_characters, VX_FAMILY_LAYOUT, frame_w, frame_h)


def pack_rmvx_character_sheet(semantic_characters, frame_w: int = FRAME_W, frame_h: int = FRAME_H) -> bytes:
    """RPG Maker VX / RGSS2 sheet; physically identical to the VX Ace sheet."""
    return pack_vx_family_standard_character_sheet(semantic_characters, frame_w, frame_h)


def pack_rmvxace_character_sheet(semantic_characters, frame_w: int = FRAME_W, frame_h: int = FRAME_H) -> bytes:
    """RPG Maker VX Ace / RGSS3 sheet; physically identical to the VX sheet."""
    return pack_vx_family_standard_character_sheet(semantic_characters, frame_w, frame_h)


def pack_wolf_character(semantic_frames: dict, frame_w: int = FRAME_W, frame_h: int = FRAME_H) -> bytes:
    """WOLF RPG Editor 3 72x128 CharaChip (see WOLF_LAYOUT)."""
    return pack_sheet_png([semantic_frames], WOLF_LAYOUT, frame_w, frame_h)


# ---------------------------------------------------------------------------
# Canonical source -> target PNG
# ---------------------------------------------------------------------------

def _extract_characters(source_bytes: bytes, source_indices) -> list:
    if source_indices is None:
        source_indices = list(range(CANONICAL_CHARACTERS))
    if len(source_indices) != CANONICAL_CHARACTERS:
        raise ValueError(f"Expected exactly 8 source character indices, got {len(source_indices)}")
    return [extract_walking_frames(source_bytes, char_idx=idx) for idx in source_indices]


def transform_canonical_to_rmxp_character(source_bytes: bytes, char_idx: int = 0) -> bytes:
    return pack_rmxp_character(extract_walking_frames(source_bytes, char_idx=char_idx))


def transform_canonical_to_rmvx_character(source_bytes: bytes, source_indices=None) -> bytes:
    return pack_rmvx_character_sheet(_extract_characters(source_bytes, source_indices))


def transform_canonical_to_rmvxace_character(source_bytes: bytes, source_indices=None) -> bytes:
    return pack_rmvxace_character_sheet(_extract_characters(source_bytes, source_indices))


def transform_canonical_to_wolf_character(source_bytes: bytes, char_idx: int = 0) -> bytes:
    return pack_wolf_character(extract_walking_frames(source_bytes, char_idx=char_idx))


def transform_rgba_to_indexed_png(rgba_bytes: bytes, width: int = CANONICAL_SHEET_W, height: int = CANONICAL_SHEET_H) -> bytes:
    """
    Converts RGBA to the 8-bit indexed PNG form used by RPG Maker 2000/2003.

    - Palette index 0 is reserved for transparency (RGB 0,0,0); every alpha-0 pixel maps to it.
    - Opaque colors get palette indices in order of first appearance, so output is deterministic.
    - Partially transparent pixels are rejected: EasyRPG draws every index except 0 fully
      opaque (docs/engine-facts.md), so such alpha cannot be represented.
    """
    if len(rgba_bytes) != width * height * 4:
        raise ValueError(f"Input RGBA buffer size mismatch: expected {width * height * 4}, got {len(rgba_bytes)}")

    palette = [(0, 0, 0)]
    color_to_index = {}
    indices = bytearray(width * height)
    for i in range(width * height):
        o = i * 4
        alpha = rgba_bytes[o + 3]
        if alpha == 0:
            continue  # index 0 is already the default
        if alpha != 255:
            raise ValueError(f"Pixel ({i % width}, {i // width}) has partial alpha {alpha}; indexed 2k-family PNGs support only alpha 0 or 255")
        rgb = (rgba_bytes[o], rgba_bytes[o + 1], rgba_bytes[o + 2])
        index = color_to_index.get(rgb)
        if index is None:
            if len(palette) >= 256:
                raise ValueError("Asset exceeds the 256-color limit of 2k-family indexed PNGs")
            index = len(palette)
            palette.append(rgb)
            color_to_index[rgb] = index
        indices[i] = index
    return create_indexed_png(width, height, palette, indices, has_trns=True)
