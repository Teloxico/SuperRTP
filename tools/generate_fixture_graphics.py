#!/usr/bin/env python3
"""
Clean-Room Synthetic Fixture Graphics Generator for SuperRTP.

Deterministically generates minimal clean-room RM2000 test fixture graphics:
  1. tests/fixtures/rm2000_min/ChipSet/ChipSet.png (480x256, 8-bit indexed)
  2. tests/fixtures/rm2000_min/System/System.png (160x80, 8-bit indexed)

Both graphics are synthesized purely from geometric code primitives with zero
proprietary or external artistic references, fulfilling the SuperRTP clean-room
provenance invariant.
"""

import os
import sys
import struct
import zlib
import hashlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from png_utils import deterministic_zlib_compress, make_png_chunk

def create_indexed_png(width, height, palette, pixel_indices, has_trns=True):
    """Encodes standard 8-bit indexed PNG with optional tRNS chunk using deterministic compression."""
    png_sig = b'\x89PNG\r\n\x1a\n'
    ihdr_data = struct.pack('>IIBBBBB', width, height, 8, 3, 0, 0, 0)
    ihdr_chunk = make_png_chunk('IHDR', ihdr_data)

    plte_data = bytearray()
    for r, g, b in palette:
        plte_data.extend([r, g, b])
    plte_chunk = make_png_chunk('PLTE', bytes(plte_data))

    trns_chunk = make_png_chunk('tRNS', b'\x00') if has_trns else b''

    raw_scanlines = bytearray()
    for y in range(height):
        raw_scanlines.append(0)  # Filter type 0
        start = y * width
        raw_scanlines.extend(pixel_indices[start:start + width])

    compressed_idat = deterministic_zlib_compress(bytes(raw_scanlines))
    idat_chunk = make_png_chunk('IDAT', compressed_idat)
    iend_chunk = make_png_chunk('IEND', b'')

    return png_sig + ihdr_chunk + plte_chunk + trns_chunk + idat_chunk + iend_chunk

def generate_minimal_chipset():
    """
    Generates minimal 480x256 ChipSet graphic.
    Tiles are 16x16 pixels.
    Fills ground tiles with synthetic grass colors.
    """
    width = 480
    height = 256
    palette = [
        (0, 0, 0),        # Index 0: Transparent background
        (46, 139, 87),    # Index 1: Base grass green (SeaGreen)
        (38, 118, 74),    # Index 2: Subtle grass shade
        (56, 160, 100),   # Index 3: Subtle grass highlight
    ]
    pixels = bytearray(width * height)

    for y in range(height):
        for x in range(width):
            # 16x16 tile grid coordinates
            tx = x % 16
            ty = y % 16
            # Subtle corner pattern for visual tile demarcation
            if (tx == 0 and ty == 0) or (tx == 15 and ty == 15):
                color_idx = 2
            elif (tx == 4 and ty == 4) or (tx == 11 and ty == 11):
                color_idx = 3
            else:
                color_idx = 1
            pixels[y * width + x] = color_idx

    return create_indexed_png(width, height, palette, pixels, has_trns=True)

def generate_minimal_system():
    """
    Generates minimal 160x80 System graphic.
    Follows RM2000 system box layout:
    - Upper-left (0,0)-(31,31): Window background gradient/fill
    - Border patterns (32..63): Window border frames
    - Text/cursor patterns (64..159)
    """
    width = 160
    height = 80
    palette = [
        (0, 0, 0),        # Index 0: Transparent
        (24, 32, 72),     # Index 1: Navy background fill
        (36, 48, 100),    # Index 2: Navy light shade
        (255, 255, 255),  # Index 3: White border
        (160, 160, 180),  # Index 4: Border shadow
    ]
    pixels = bytearray(width * height)

    # Fill default background with transparent index 0
    # Window box pattern in top-left 32x32:
    for y in range(32):
        for x in range(32):
            if x == 0 or x == 31 or y == 0 or y == 31:
                pixels[y * width + x] = 3  # Border
            elif x == 1 or x == 30 or y == 1 or y == 30:
                pixels[y * width + x] = 4  # Shadow
            else:
                # Gradient fill
                pixels[y * width + x] = 2 if (x + y) % 4 == 0 else 1

    # Border frame graphics in (32..63, 0..31):
    for y in range(32):
        for x in range(32, 64):
            if x == 32 or x == 63 or y == 0 or y == 31:
                pixels[y * width + x] = 3
            else:
                pixels[y * width + x] = 1

    return create_indexed_png(width, height, palette, pixels, has_trns=True)

def main():
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    fixture_dir = os.path.join(repo_root, "tests", "fixtures", "rm2000_min")

    chipset_dir = os.path.join(fixture_dir, "ChipSet")
    system_dir = os.path.join(fixture_dir, "System")
    os.makedirs(chipset_dir, exist_ok=True)
    os.makedirs(system_dir, exist_ok=True)

    chipset_bytes = generate_minimal_chipset()
    chipset_path = os.path.join(chipset_dir, "ChipSet.png")
    with open(chipset_path, "wb") as f:
        f.write(chipset_bytes)
    chipset_hash = hashlib.sha256(chipset_bytes).hexdigest()

    system_bytes = generate_minimal_system()
    system_path = os.path.join(system_dir, "System.png")
    with open(system_path, "wb") as f:
        f.write(system_bytes)
    system_hash = hashlib.sha256(system_bytes).hexdigest()

    print(f"Generated ChipSet: {chipset_path} (SHA-256: {chipset_hash})")
    print(f"Generated System:  {system_path} (SHA-256: {system_hash})")

if __name__ == "__main__":
    main()
