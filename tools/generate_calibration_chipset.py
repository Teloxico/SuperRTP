#!/usr/bin/env python3
"""
Clean-Room Canonical Calibration ChipSet Generator for SuperRTP.

Deterministically synthesizes a 480x256 32-bit RGBA canonical ChipSet asset
consisting of 30 columns x 16 rows of 16x16 tile units:
  - Columns 0..11 (Blocks A, B, C, D): Deterministic clean-room placeholder tiles
    (labeled as unverified autotile placeholders, outside Task 3 scope).
  - Columns 12..17, Rows 0..15 (Block E Bank 1, Lower-layer fixed tiles 5000..5095):
    Tile 5000 at col 12, row 0 features a verified blue/cyan/yellow geometric pattern.
  - Columns 18..23, Rows 0..7 (Block E Bank 2, Lower-layer fixed tiles 5096..5143):
    Tile 5096 at col 18, row 0 features a verified green/lime/magenta geometric pattern.
  - Columns 18..23, Rows 8..15 (Block F Bank 1, Upper-layer fixed tiles 10000..10047):
    Tile 10000 at col 18, row 8 features an opaque red cross over transparent background
    for upper/lower layer composition and transparency verification.
  - Columns 24..29, Rows 0..15 (Block F Bank 2, Upper-layer fixed tiles 10048..10143):
    Tile 10048 at col 24, row 0 features an opaque orange diamond over transparent background.

Total color palette is strictly limited (< 32 colors) with index 0 reserved for transparency.
Contains ZERO proprietary RTP creative content; 100% CC0-1.0 geometric primitives.
"""

import os
import sys
import json
import struct
import zlib
import hashlib

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))
from png_utils import deterministic_zlib_compress, make_png_chunk

WIDTH = 480
HEIGHT = 256
TILE_SIZE = 16
COLS = WIDTH // TILE_SIZE   # 30
ROWS = HEIGHT // TILE_SIZE  # 16

# Color definitions (R, G, B, A)
COLOR_TRANSPARENT = (0, 0, 0, 0)
COLOR_GRID_BG     = (18, 22, 32, 255)
COLOR_GRID_BORDER = (36, 44, 62, 255)
COLOR_AUTOTILE_BG = (28, 28, 38, 255)
COLOR_AUTOTILE_BD = (55, 55, 75, 255)

# Tile 5000 colors (Block E Bank 1)
COLOR_5000_BG     = (12, 48, 160, 255)   # Deep blue
COLOR_5000_BORDER = (0, 240, 255, 255)   # Cyan
COLOR_5000_CENTER = (255, 220, 30, 255)  # Bright yellow

# Tile 5096 colors (Block E Bank 2)
COLOR_5096_BG     = (15, 120, 45, 255)   # Forest green
COLOR_5096_BORDER = (50, 255, 80, 255)   # Lime
COLOR_5096_CENTER = (250, 40, 200, 255)  # Magenta

# Tile 10000 colors (Block F Bank 1: Upper layer transparency test)
COLOR_10000_FG    = (230, 30, 30, 255)   # Bright red cross
COLOR_10000_BD    = (130, 15, 15, 255)   # Dark red border

# Tile 10048 colors (Block F Bank 2: Upper layer fixed tile)
COLOR_10048_FG    = (255, 130, 10, 255)  # Bright orange
COLOR_10048_BD    = (150, 65, 5, 255)    # Dark orange border

# Filler colors for other fixed tiles
COLOR_E_FILLER_BG = (22, 30, 46, 255)
COLOR_E_FILLER_BD = (42, 58, 86, 255)
COLOR_F_FILLER_FG = (100, 150, 220, 255)
COLOR_F_FILLER_BD = (50, 80, 140, 255)

def create_master_png(width, height, rgba_data):
    """Creates a standard 32-bit RGBA PNG for the canonical master image."""
    png_sig = b'\x89PNG\r\n\x1a\n'
    ihdr_data = struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)
    ihdr_chunk = make_png_chunk('IHDR', ihdr_data)

    scanlines = bytearray()
    bpp = 4
    for y in range(height):
        scanlines.append(0)  # filter None
        start = y * width * bpp
        scanlines.extend(rgba_data[start:start + width * bpp])

    compressed_idat = deterministic_zlib_compress(bytes(scanlines))
    idat_chunk = make_png_chunk('IDAT', compressed_idat)
    iend_chunk = make_png_chunk('IEND', b'')

    return png_sig + ihdr_chunk + idat_chunk + iend_chunk

def generate_chipset():
    # 480x256 pixels, each (r, g, b, a)
    pixels = [[COLOR_TRANSPARENT for _ in range(WIDTH)] for _ in range(HEIGHT)]

    for row in range(ROWS):
        for col in range(COLS):
            tile_x = col * TILE_SIZE
            tile_y = row * TILE_SIZE

            # 1. Blocks A, B, C, D (Cols 0..11): Autotiles (out of scope for Task 3)
            if col < 12:
                for py in range(TILE_SIZE):
                    for px in range(TILE_SIZE):
                        x = tile_x + px
                        y = tile_y + py
                        if px == 0 or px == TILE_SIZE - 1 or py == 0 or py == TILE_SIZE - 1:
                            pixels[y][x] = COLOR_AUTOTILE_BD
                        elif (px + py) % 4 == 0:
                            pixels[y][x] = COLOR_AUTOTILE_BD
                        else:
                            pixels[y][x] = COLOR_AUTOTILE_BG

            # 2. Block E Bank 1 (Cols 12..17, Rows 0..15): Lower layer tiles 5000..5095
            elif 12 <= col <= 17:
                is_tile_5000 = (col == 12 and row == 0)
                for py in range(TILE_SIZE):
                    for px in range(TILE_SIZE):
                        x = tile_x + px
                        y = tile_y + py
                        if is_tile_5000:
                            if px == 0 or px == TILE_SIZE - 1 or py == 0 or py == TILE_SIZE - 1:
                                pixels[y][x] = COLOR_5000_BORDER
                            elif 5 <= px <= 10 and 5 <= py <= 10:
                                pixels[y][x] = COLOR_5000_CENTER
                            else:
                                pixels[y][x] = COLOR_5000_BG
                        else:
                            # Other Block E Bank 1 tiles
                            if px == 0 or px == TILE_SIZE - 1 or py == 0 or py == TILE_SIZE - 1:
                                pixels[y][x] = COLOR_E_FILLER_BD
                            else:
                                pixels[y][x] = COLOR_E_FILLER_BG

            # 3. Cols 18..23:
            #    Rows 0..7: Block E Bank 2 (Lower layer tiles 5096..5143)
            #    Rows 8..15: Block F Bank 1 (Upper layer tiles 10000..10047)
            elif 18 <= col <= 23:
                if row < 8:
                    # Block E Bank 2
                    is_tile_5096 = (col == 18 and row == 0)
                    for py in range(TILE_SIZE):
                        for px in range(TILE_SIZE):
                            x = tile_x + px
                            y = tile_y + py
                            if is_tile_5096:
                                if px == 0 or px == TILE_SIZE - 1 or py == 0 or py == TILE_SIZE - 1:
                                    pixels[y][x] = COLOR_5096_BORDER
                                elif 5 <= px <= 10 and 5 <= py <= 10:
                                    pixels[y][x] = COLOR_5096_CENTER
                                else:
                                    pixels[y][x] = COLOR_5096_BG
                            else:
                                if px == 0 or px == TILE_SIZE - 1 or py == 0 or py == TILE_SIZE - 1:
                                    pixels[y][x] = COLOR_E_FILLER_BD
                                else:
                                    pixels[y][x] = COLOR_E_FILLER_BG
                else:
                    # Block F Bank 1 (Upper layer)
                    is_tile_10000 = (col == 18 and row == 8)
                    for py in range(TILE_SIZE):
                        for px in range(TILE_SIZE):
                            x = tile_x + px
                            y = tile_y + py
                            if is_tile_10000:
                                # Red cross on transparent background
                                in_vert = (6 <= px <= 9 and 2 <= py <= 13)
                                in_horiz = (2 <= px <= 13 and 6 <= py <= 9)
                                is_vert_bd = (5 <= px <= 10 and 1 <= py <= 14) and (px in (5, 10) or py in (1, 14))
                                is_horiz_bd = (1 <= px <= 14 and 5 <= py <= 10) and (px in (1, 14) or py in (5, 10))

                                if in_vert or in_horiz:
                                    pixels[y][x] = COLOR_10000_FG
                                elif is_vert_bd or is_horiz_bd:
                                    pixels[y][x] = COLOR_10000_BD
                                else:
                                    pixels[y][x] = COLOR_TRANSPARENT
                            else:
                                # Other Block F Bank 1 tiles: small centered square on transparent bg
                                if 6 <= px <= 9 and 6 <= py <= 9:
                                    pixels[y][x] = COLOR_F_FILLER_FG
                                else:
                                    pixels[y][x] = COLOR_TRANSPARENT

            # 4. Block F Bank 2 (Cols 24..29, Rows 0..15): Upper layer tiles 10048..10143
            elif 24 <= col <= 29:
                is_tile_10048 = (col == 24 and row == 0)
                for py in range(TILE_SIZE):
                    for px in range(TILE_SIZE):
                        x = tile_x + px
                        y = tile_y + py
                        if is_tile_10048:
                            # Diamond on transparent background: |px - 7.5| + |py - 7.5| <= 6
                            dist = abs(px - 7.5) + abs(py - 7.5)
                            if dist <= 5.0:
                                pixels[y][x] = COLOR_10048_FG
                            elif dist <= 6.5:
                                pixels[y][x] = COLOR_10048_BD
                            else:
                                pixels[y][x] = COLOR_TRANSPARENT
                        else:
                            # Small centered diamond on transparent bg
                            dist = abs(px - 7.5) + abs(py - 7.5)
                            if dist <= 3.5:
                                pixels[y][x] = COLOR_F_FILLER_FG
                            else:
                                pixels[y][x] = COLOR_TRANSPARENT

    # Flatten to bytes
    raw_rgba = bytearray(WIDTH * HEIGHT * 4)
    idx = 0
    unique_colors = set()
    for y in range(HEIGHT):
        for x in range(WIDTH):
            r, g, b, a = pixels[y][x]
            unique_colors.add((r, g, b, a))
            raw_rgba[idx]     = r
            raw_rgba[idx + 1] = g
            raw_rgba[idx + 2] = b
            raw_rgba[idx + 3] = a
            idx += 4

    print(f"Generated ChipSet: {WIDTH}x{HEIGHT} ({COLS}x{ROWS} tiles), unique RGBA colors: {len(unique_colors)}")
    rgba_bytes = bytes(raw_rgba)
    master_png_data = create_master_png(WIDTH, HEIGHT, rgba_bytes)
    return rgba_bytes, master_png_data

def main():
    rgba_bytes, master_png_data = generate_chipset()
    sha256_hash = hashlib.sha256(rgba_bytes).hexdigest()
    print(f"Canonical ChipSet RGBA SHA-256: {sha256_hash}")

    rgba_path = os.path.join(REPO_ROOT, "registry", "assets", "test_calibration_map_chipset.rgba")
    with open(rgba_path, "wb") as f:
        f.write(rgba_bytes)
    print(f"Written: {rgba_path}")

    master_png_path = os.path.join(REPO_ROOT, "registry", "assets", "test_calibration_map_chipset.master.png")
    with open(master_png_path, "wb") as f:
        f.write(master_png_data)
    print(f"Written: {master_png_path}")

    # Compute generator script hash
    script_path = os.path.abspath(__file__)
    with open(script_path, "rb") as f:
        generator_sha256 = hashlib.sha256(f.read()).hexdigest()

    # Asset metadata
    asset_meta = {
        "id": "test.calibration.map-chipset",
        "name": "Calibration Map ChipSet (Fixed-Tile)",
        "description": "Project-owned clean-room geometric calibration tileset for RM2000/RM2003 ChipSet compatibility testing (Blocks E & F fixed tiles).",
        "type": "chipset",
        "format": "rgba32",
        "dimensions": {
            "width": WIDTH,
            "height": HEIGHT
        },
        "palette": {
            "max_colors": 256,
            "transparent_index": 0
        },
        "test_only": True,
        "license": "CC0-1.0",
        "file": "registry/assets/test_calibration_map_chipset.rgba",
        "master_png": "registry/assets/test_calibration_map_chipset.master.png",
        "sha256": sha256_hash
    }
    meta_path = os.path.join(REPO_ROOT, "registry", "assets", "test_calibration_map_chipset.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(asset_meta, f, indent=2)
    print(f"Written: {meta_path}")

    # Provenance record
    prov_record = {
        "asset_id": "test.calibration.map-chipset",
        "canonical_path": "registry/assets/test_calibration_map_chipset.rgba",
        "sha256": sha256_hash,
        "license": "CC0-1.0",
        "source_type": "project_synthetic",
        "creator": "SuperRTP Project",
        "creation_tool": "tools/generate_calibration_chipset.py",
        "clean_room_attestation": {
            "proprietary_rtp_derived": False,
            "openrtp_derived": False,
            "external_art_used": False,
            "ai_generation_used": False,
            "geometric_primitives_only": True,
            "notes": "100% project-owned synthetic clean-room calibration ChipSet generated deterministically from geometric code. Contains verified test patterns for Block E (IDs 5000, 5096) and Block F (IDs 10000, 10048) with transparency composition."
        },
        "specification": {
            "rpg_engine": "RPG Maker 2000 / RPG Maker 2003 / EasyRPG Player",
            "asset_class": "ChipSet",
            "notes": "Test-only compatibility calibration fixture for 2k family ChipSet fixed-tile vertical slice (Blocks E & F)."
        },
        "test_only": True
    }
    prov_path = os.path.join(REPO_ROOT, "registry", "provenance", "test_calibration_map_chipset.json")
    with open(prov_path, "w", encoding="utf-8") as f:
        json.dump(prov_record, f, indent=2)
    print(f"Written: {prov_path}")

if __name__ == "__main__":
    main()
