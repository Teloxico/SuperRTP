#!/usr/bin/env python3
"""
Clean-Room Synthetic Calibration CharSet Generator for SuperRTP.

Generates a neutral canonical walking character sprite sheet:
- Total dimensions: 288 x 256 pixels
- Character layout: 8 characters arranged in a 4x2 grid (72 x 128 per character)
- Frame layout: 3 columns x 4 rows per character (24 x 32 per frame)
  - Col 0: Left step, Col 1: Standing (idle), Col 2: Right step
  - Physical RM2000/EasyRPG Row Order:
      Row 0: Facing Up (facing 0)
      Row 1: Facing Right (facing 1)
      Row 2: Facing Down (facing 2)
      Row 3: Facing Left (facing 3)
- Neutral format: 32-bit RGBA pixel matrix (uncompressed bytes + master PNG)
- Target-specific transformations (e.g. 8-bit indexed palette, tRNS) are handled
  downstream by tools/build_target.py.
"""

import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from png_utils import create_rgba_png

# Color theme per character slot 0..7. Runtime verifiers import this to know which
# outline color each slot's arrow tip must have.
SLOT_THEMES = [
    # Slot 0 (Protagonist / Actor 1): Cyan / Amber / Gold
    {"body": (0, 210, 230), "outline": (10, 40, 70), "accent": (255, 230, 80), "foot": (240, 160, 20)},
    # Slot 1: Emerald / Forest / Lemon
    {"body": (40, 220, 120), "outline": (10, 60, 30), "accent": (220, 255, 80), "foot": (180, 200, 30)},
    # Slot 2: Crimson / Maroon / Orange
    {"body": (240, 60, 60), "outline": (70, 10, 20), "accent": (255, 180, 60), "foot": (220, 100, 30)},
    # Slot 3: Indigo / Deep Blue / Sky
    {"body": (80, 120, 250), "outline": (20, 20, 80), "accent": (140, 220, 255), "foot": (60, 80, 200)},
    # Slot 4: Magenta / Dark Purple / Pink
    {"body": (220, 60, 200), "outline": (60, 10, 60), "accent": (255, 160, 240), "foot": (180, 40, 140)},
    # Slot 5: Amber / Rust / Cream
    {"body": (250, 160, 30), "outline": (70, 40, 10), "accent": (255, 240, 160), "foot": (200, 110, 20)},
    # Slot 6: Teal / Slate / Mint
    {"body": (30, 200, 190), "outline": (20, 50, 60), "accent": (180, 255, 230), "foot": (20, 140, 130)},
    # Slot 7: Silver / Charcoal / Bronze
    {"body": (210, 215, 220), "outline": (50, 55, 60), "accent": (255, 255, 255), "foot": (150, 110, 70)},
]


def generate_canonical_rgba():
    width = 288
    height = 256
    # 4 bytes per pixel: R, G, B, A (0 = fully transparent)
    rgba = bytearray(width * height * 4)


    # Frame boundary calibration color (dark subtle tick)
    calibration_color = (30, 30, 35)

    for char_idx in range(8):
        char_grid_x = char_idx % 4
        char_grid_y = char_idx // 4
        char_base_x = char_grid_x * 72
        char_base_y = char_grid_y * 128
        theme = SLOT_THEMES[char_idx]

        for row in range(4):        # 4 directions
            for col in range(3):    # 3 walking frames
                fx0 = char_base_x + col * 24
                fy0 = char_base_y + row * 32

                def set_px(lx, ly, rgb):
                    if 0 <= lx < 24 and 0 <= ly < 32:
                        idx = ((fy0 + ly) * width + (fx0 + lx)) * 4
                        rgba[idx] = rgb[0]
                        rgba[idx + 1] = rgb[1]
                        rgba[idx + 2] = rgb[2]
                        rgba[idx + 3] = 255  # Fully opaque

                # 1. Subtle 2x2 corner calibration markers
                for cx, cy in [(0,0), (1,0), (0,1), (23,0), (22,0), (23,1),
                               (0,31), (1,31), (0,30), (23,31), (22,31), (23,30)]:
                    set_px(cx, cy, calibration_color)

                # 2. Feet / Step markers at bottom (ly = 24..28)
                # Col 0: Left step (left foot forward/lower, right foot back)
                # Col 1: Standing (center feet symmetric)
                # Col 2: Right step (right foot forward/lower, left foot back)
                if col == 1:  # Center idle standing
                    for ly in range(25, 28):
                        for lx in range(7, 10):
                            set_px(lx, ly, theme["foot"])
                        for lx in range(14, 17):
                            set_px(lx, ly, theme["foot"])
                elif col == 0:  # Left step forward
                    for ly in range(26, 29):
                        for lx in range(6, 10):
                            set_px(lx, ly, theme["foot"])
                    for ly in range(24, 26):
                        for lx in range(14, 17):
                            set_px(lx, ly, theme["foot"])
                elif col == 2:  # Right step forward
                    for ly in range(24, 26):
                        for lx in range(7, 10):
                            set_px(lx, ly, theme["foot"])
                    for ly in range(26, 29):
                        for lx in range(14, 18):
                            set_px(lx, ly, theme["foot"])

                # 3. Geometric Directional Arrow Body
                # CRITICAL PHYSICAL RM2000 ROW ORDER:
                # Row 0: Facing Up (facing 0)
                # Row 1: Facing Right (facing 1)
                # Row 2: Facing Down (facing 2)
                # Row 3: Facing Left (facing 3)

                if row == 0:  # UP (^)
                    for ly in range(5, 23):
                        if ly <= 13:
                            # Pointing up towards tip at (11.5, 5)
                            span = ly - 5
                            left_edge = 11 - span
                            right_edge = 12 + span
                            for lx in range(left_edge, right_edge + 1):
                                is_outline = (ly == 5 or lx == left_edge or lx == right_edge)
                                set_px(lx, ly, theme["outline"] if is_outline else theme["body"])
                        else:
                            # Lower wings and inner notch
                            span = ly - 13
                            left_edge = 3 + span // 2
                            right_edge = 20 - span // 2
                            notch_left = 11 - span
                            notch_right = 12 + span
                            for lx in range(3, 21):
                                if ly > 15 and notch_left <= lx <= notch_right:
                                    continue
                                is_outline = (lx == 3 or lx == 20 or ly == 22 or
                                              (ly <= 19 and (lx == notch_left or lx == notch_right)))
                                set_px(lx, ly, theme["outline"] if is_outline else theme["body"])
                    # Center accent core
                    for ly in range(11, 14):
                        for lx in range(10, 14):
                            set_px(lx, ly, theme["accent"])

                elif row == 1:  # RIGHT (>)
                    for lx in range(4, 20):
                        if lx >= 11:
                            # Tip pointing right towards x=19
                            span = 19 - lx
                            top_edge = 13 - span
                            bottom_edge = 14 + span
                            for ly in range(top_edge, bottom_edge + 1):
                                is_outline = (lx == 19 or ly == top_edge or ly == bottom_edge)
                                set_px(lx, ly, theme["outline"] if is_outline else theme["body"])
                        else:
                            # Back notch
                            span = lx - 4
                            inner_top = 10 + span // 2
                            inner_bot = 17 - span // 2
                            for ly in range(6, 22):
                                if inner_top <= ly <= inner_bot and lx < 9:
                                    continue
                                is_outline = (lx == 4 or ly == 6 or ly == 21 or
                                              (lx >= 8 and (ly == inner_top or ly == inner_bot)))
                                set_px(lx, ly, theme["outline"] if is_outline else theme["body"])
                    # Center accent core
                    for ly in range(12, 16):
                        for lx in range(11, 15):
                            set_px(lx, ly, theme["accent"])

                elif row == 2:  # DOWN (v)
                    for ly in range(5, 23):
                        if ly <= 13:
                            # Upper wings
                            left_edge = max(3, 11 - (ly - 5) * 1)
                            right_edge = min(20, 12 + (ly - 5) * 1)
                            notch_left = 11 - (ly - 5) // 2
                            notch_right = 12 + (ly - 5) // 2
                            for lx in range(left_edge, right_edge + 1):
                                if ly < 9 and notch_left <= lx <= notch_right:
                                    continue
                                is_outline = (lx == left_edge or lx == right_edge or
                                              (ly >= 8 and (lx == notch_left or lx == notch_right)))
                                set_px(lx, ly, theme["outline"] if is_outline else theme["body"])
                        else:
                            # Lower tip pointing down to (11.5, 21)
                            span = 21 - ly
                            left_edge = 11 - span
                            right_edge = 12 + span
                            for lx in range(left_edge, right_edge + 1):
                                is_outline = (lx == left_edge or lx == right_edge or ly == 21)
                                set_px(lx, ly, theme["outline"] if is_outline else theme["body"])
                    # Center accent core
                    for ly in range(11, 14):
                        for lx in range(10, 14):
                            set_px(lx, ly, theme["accent"])

                elif row == 3:  # LEFT (<)
                    for lx in range(4, 20):
                        if lx <= 12:
                            # Tip pointing left towards x=4
                            span = lx - 4
                            top_edge = 13 - span
                            bottom_edge = 14 + span
                            for ly in range(top_edge, bottom_edge + 1):
                                is_outline = (lx == 4 or ly == top_edge or ly == bottom_edge)
                                set_px(lx, ly, theme["outline"] if is_outline else theme["body"])
                        else:
                            # Back notch
                            span = 19 - lx
                            top_edge = 6 + (12 - lx) // 2
                            bottom_edge = 21 - (12 - lx) // 2
                            inner_top = 10 + span // 2
                            inner_bot = 17 - span // 2
                            for ly in range(6, 22):
                                if inner_top <= ly <= inner_bot and lx > 14:
                                    continue
                                is_outline = (lx == 19 or ly == 6 or ly == 21 or
                                              (lx <= 15 and (ly == inner_top or ly == inner_bot)))
                                set_px(lx, ly, theme["outline"] if is_outline else theme["body"])
                    # Center accent core
                    for ly in range(12, 16):
                        for lx in range(9, 13):
                            set_px(lx, ly, theme["accent"])

    return bytes(rgba)

def generate_calibration_charset():
    rgba_bytes = generate_canonical_rgba()
    master_png = create_rgba_png(288, 256, rgba_bytes)
    return rgba_bytes, master_png

def main():
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assets_dir = os.path.join(repo_root, "registry", "assets")
    os.makedirs(assets_dir, exist_ok=True)

    rgba_bytes = generate_canonical_rgba()
    raw_path = os.path.join(assets_dir, "test_calibration_walking_character.rgba")
    with open(raw_path, "wb") as f:
        f.write(rgba_bytes)

    master_png = create_rgba_png(288, 256, rgba_bytes)
    master_png_path = os.path.join(assets_dir, "test_calibration_walking_character_master.png")
    with open(master_png_path, "wb") as f:
        f.write(master_png)

    sha256_hash = hashlib.sha256(rgba_bytes).hexdigest()

    meta = {
        "id": "test.calibration.walking-character",
        "name": "2k-Family Calibration Walking Character Sprite Sheet (RM2000 / RM2003)",
        "description": "Synthetic clean-room geometric calibration sprite sheet for RPG Maker 2000 and 2003 CharSet verification",
        "type": "charset",
        "format": "image/x-rgba-raw; 32-bit",
        "dimensions": {
            "width": 288,
            "height": 256
        },
        "grid": {
            "characters_x": 4,
            "characters_y": 2,
            "frame_width": 24,
            "frame_height": 32,
            "columns_per_character": 3,
            "rows_per_character": 4
        },
        "directions": {
            "row_0": "UP",
            "row_1": "RIGHT",
            "row_2": "DOWN",
            "row_3": "LEFT"
        },
        "animation_columns": {
            "col_0": "STEP_LEFT",
            "col_1": "IDLE",
            "col_2": "STEP_RIGHT"
        },
        "test_only": True,
        "license": "CC0-1.0",
        "file": "registry/assets/test_calibration_walking_character.rgba",
        "master_png": "registry/assets/test_calibration_walking_character_master.png",
        "sha256": sha256_hash
    }

    meta_path = os.path.join(assets_dir, "test_calibration_walking_character.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    print(f"Generated canonical RGBA source: {raw_path}")
    print(f"Generated master PNG preview: {master_png_path}")
    print(f"Metadata written: {meta_path}")
    print(f"SHA-256: {sha256_hash}")

if __name__ == "__main__":
    main()
