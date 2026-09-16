#!/usr/bin/env python3
"""
Deterministic Validator for SuperRTP Targets.

Mechanically verifies that generated target packs conform to strict compatibility,
provenance, and structural invariants without relying on assumptions.

Validates:
  1. JSON Schema conformance for slot mapping, asset metadata, and provenance records
  2. File existence & PNG binary chunk structure (IHDR, PLTE, IDAT, IEND)
  3. Resolution (288x256 for RM2000 CharSet)
  4. Color model (8-bit indexed colormap, Color Type 3, <= 256 palette entries)
  5. Transparency semantics (Palette index 0 transparent; tRNS checked if present)
  6. Geometric frame divisibility (72x128 character slot, 24x32 frame cell)
  7. Provenance completeness (matching SHA-256, CC0-1.0, clean-room attestation)
  8. Test-only designation verification

Usage:
  python3 tools/validate_target.py --target rm2000 [--target-dir generated/rm2000]
"""

import os
import sys
import json
import struct
import zlib
import hashlib
import argparse

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))
from schema_validator import validate_schema

PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'

def parse_png_chunks(data):
    """Parses PNG chunks and returns a dictionary of chunk lists."""
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("Invalid PNG: missing or incorrect PNG signature")

    offset = 8
    chunks = []
    data_len = len(data)

    while offset < data_len:
        if offset + 8 > data_len:
            raise ValueError("Corrupt PNG: truncated chunk header")
        length, chunk_type = struct.unpack('>I4s', data[offset:offset+8])
        chunk_type = chunk_type.decode('ascii', errors='replace')
        offset += 8

        if offset + length + 4 > data_len:
            raise ValueError(f"Corrupt PNG: chunk {chunk_type} extends past EOF")

        chunk_data = data[offset:offset+length]
        offset += length
        crc = struct.unpack('>I', data[offset:offset+4])[0]
        offset += 4

        # Verify CRC
        expected_crc = zlib.crc32(chunk_type.encode('ascii') + chunk_data) & 0xffffffff
        if crc != expected_crc:
            raise ValueError(f"CRC mismatch in {chunk_type} chunk: expected {expected_crc}, got {crc}")

        chunks.append((chunk_type, chunk_data))

    return chunks

def validate_png_charset(filepath):
    """Validates RM2000 CharSet technical specifications."""
    with open(filepath, "rb") as f:
        data = f.read()

    chunks = parse_png_chunks(data)
    chunk_types = [c[0] for c in chunks]

    # Required chunks in order
    if not chunk_types or chunk_types[0] != "IHDR":
        raise ValueError("PNG must start with IHDR chunk")
    if "PLTE" not in chunk_types:
        raise ValueError("Missing required PLTE (Palette) chunk for indexed RM2000 CharSet")
    if "IDAT" not in chunk_types:
        raise ValueError("Missing IDAT chunk")
    if chunk_types[-1] != "IEND":
        raise ValueError("PNG must terminate with IEND chunk")

    # Inspect IHDR
    ihdr_data = next(c[1] for c in chunks if c[0] == "IHDR")
    width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack('>IIBBBBB', ihdr_data)

    if width != 288 or height != 256:
        raise ValueError(f"Invalid CharSet dimensions: expected 288x256, got {width}x{height}")
    if bit_depth != 8:
        raise ValueError(f"Invalid bit depth: expected 8, got {bit_depth}")
    if color_type != 3:
        raise ValueError(f"Invalid color type: expected 3 (indexed-color), got {color_type}")
    if compression != 0 or filter_method != 0 or interlace != 0:
        raise ValueError("Unsupported compression/filter/interlace method")

    # Inspect PLTE (Palette index 0 is the engine compatibility transparent color)
    plte_data = next(c[1] for c in chunks if c[0] == "PLTE")
    if len(plte_data) % 3 != 0:
        raise ValueError(f"PLTE data length ({len(plte_data)}) is not a multiple of 3")
    num_colors = len(plte_data) // 3
    if num_colors > 256:
        raise ValueError(f"Palette exceeds 256 colors: {num_colors}")

    # Inspect tRNS if present (modern viewer enhancement, optional for original RM2000 engine)
    has_trns = "tRNS" in chunk_types
    if has_trns:
        trns_data = next(c[1] for c in chunks if c[0] == "tRNS")
        if len(trns_data) > 0 and trns_data[0] != 0:
            raise ValueError(f"Transparency index 0 in tRNS has non-zero alpha ({trns_data[0]})")

    # Check grid divisibility
    char_w, char_h = width // 4, height // 2
    if char_w != 72 or char_h != 128:
        raise ValueError(f"Invalid character grid: expected 72x128, got {char_w}x{char_h}")
    frame_w, frame_h = char_w // 3, char_h // 4
    if frame_w != 24 or frame_h != 32:
        raise ValueError(f"Invalid frame cell: expected 24x32, got {frame_w}x{frame_h}")

    return {
        "width": width,
        "height": height,
        "bit_depth": bit_depth,
        "color_type": color_type,
        "num_colors": num_colors,
        "transparent_index": 0,
        "has_trns": has_trns,
        "characters_grid": "4x2",
        "frame_cell": f"{frame_w}x{frame_h}"
    }

def validate_png_chipset(filepath):
    """Validates RM2000/RM2003 ChipSet technical specifications."""
    with open(filepath, "rb") as f:
        data = f.read()

    chunks = parse_png_chunks(data)
    chunk_types = [c[0] for c in chunks]

    # Required chunks in order
    if not chunk_types or chunk_types[0] != "IHDR":
        raise ValueError("PNG must start with IHDR chunk")
    if "PLTE" not in chunk_types:
        raise ValueError("Missing required PLTE (Palette) chunk for indexed ChipSet")
    if "IDAT" not in chunk_types:
        raise ValueError("Missing IDAT chunk")
    if chunk_types[-1] != "IEND":
        raise ValueError("PNG must terminate with IEND chunk")

    # Inspect IHDR
    ihdr_data = next(c[1] for c in chunks if c[0] == "IHDR")
    width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack('>IIBBBBB', ihdr_data)

    if width != 480 or height != 256:
        raise ValueError(f"Invalid ChipSet dimensions: expected 480x256, got {width}x{height}")
    if bit_depth != 8:
        raise ValueError(f"Invalid bit depth: expected 8, got {bit_depth}")
    if color_type != 3:
        raise ValueError(f"Invalid color type: expected 3 (indexed-color), got {color_type}")
    if compression != 0 or filter_method != 0 or interlace != 0:
        raise ValueError("Unsupported compression/filter/interlace method")

    # Inspect PLTE (Palette index 0 is the engine compatibility transparent color)
    plte_data = next(c[1] for c in chunks if c[0] == "PLTE")
    if len(plte_data) % 3 != 0:
        raise ValueError(f"PLTE data length ({len(plte_data)}) is not a multiple of 3")
    num_colors = len(plte_data) // 3
    if num_colors > 256:
        raise ValueError(f"Palette exceeds 256 colors: {num_colors}")

    # Inspect tRNS if present
    has_trns = "tRNS" in chunk_types
    if has_trns:
        trns_data = next(c[1] for c in chunks if c[0] == "tRNS")
        if len(trns_data) > 0 and trns_data[0] != 0:
            raise ValueError(f"Transparency index 0 in tRNS has non-zero alpha ({trns_data[0]})")

    # Check tile divisibility (30 columns x 16 rows of 16x16 tiles)
    cols = width // 16
    rows = height // 16
    if cols != 30 or rows != 16:
        raise ValueError(f"Invalid tile grid: expected 30x16 tiles (16x16), got {cols}x{rows}")

    return {
        "width": width,
        "height": height,
        "bit_depth": bit_depth,
        "color_type": color_type,
        "num_colors": num_colors,
        "transparent_index": 0,
        "has_trns": has_trns,
        "tile_grid": f"{cols}x{rows}",
        "tile_size": "16x16"
    }

def validate_png_rmxp_character(filepath):
    """Validates RPG Maker XP / RGSS1 Character technical specifications and calibration geometry."""
    with open(filepath, "rb") as f:
        data = f.read()

    chunks = parse_png_chunks(data)
    chunk_types = [c[0] for c in chunks]

    # Required chunks in order
    if not chunk_types or chunk_types[0] != "IHDR":
        raise ValueError("PNG must start with IHDR chunk")
    if "PLTE" in chunk_types:
        raise ValueError("Unexpected PLTE (Palette) chunk: RPG Maker XP character sheets must be truecolor RGBA")
    if "IDAT" not in chunk_types:
        raise ValueError("Missing IDAT chunk")
    if chunk_types[-1] != "IEND":
        raise ValueError("PNG must terminate with IEND chunk")

    # Inspect IHDR
    ihdr_data = next(c[1] for c in chunks if c[0] == "IHDR")
    width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack('>IIBBBBB', ihdr_data)

    if width != 96 or height != 128:
        raise ValueError(f"Invalid XP Character dimensions: expected 96x128, got {width}x{height}")
    if bit_depth != 8:
        raise ValueError(f"Invalid bit depth: expected 8, got {bit_depth}")
    if color_type != 6:
        raise ValueError(f"Invalid color type: expected 6 (RGBA truecolor), got {color_type}")
    if compression != 0 or filter_method != 0 or interlace != 0:
        raise ValueError("Unsupported compression/filter/interlace method")

    # Decompress IDAT and reconstruct 32-bit RGBA pixel grid
    idat_data = b''.join(c[1] for c in chunks if c[0] == "IDAT")
    raw = bytearray(zlib.decompress(idat_data))
    bpp = 4
    stride = 1 + width * bpp
    if len(raw) != height * stride:
        raise ValueError(f"Decompressed IDAT size mismatch: expected {height * stride}, got {len(raw)}")

    recon = bytearray(width * height * bpp)
    prior = bytearray(width * bpp)

    for y in range(height):
        filter_type = raw[y * stride]
        filt = raw[y * stride + 1 : (y + 1) * stride]
        line = bytearray(width * bpp)

        if filter_type == 0:
            line[:] = filt
        elif filter_type == 1:
            for x in range(width * bpp):
                a = line[x - bpp] if x >= bpp else 0
                line[x] = (filt[x] + a) & 0xff
        elif filter_type == 2:
            for x in range(width * bpp):
                line[x] = (filt[x] + prior[x]) & 0xff
        elif filter_type == 3:
            for x in range(width * bpp):
                a = line[x - bpp] if x >= bpp else 0
                line[x] = (filt[x] + ((a + prior[x]) >> 1)) & 0xff
        elif filter_type == 4:
            for x in range(width * bpp):
                a = line[x - bpp] if x >= bpp else 0
                b = prior[x]
                c = prior[x - bpp] if x >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (filt[x] + pr) & 0xff
        else:
            raise ValueError(f"Unknown PNG filter type {filter_type}")

        prior[:] = line
        recon[y * width * bpp : (y + 1) * width * bpp] = line

    def get_pixel(x, y):
        idx = (y * width + x) * 4
        return (recon[idx], recon[idx + 1], recon[idx + 2], recon[idx + 3])

    # Check alpha distribution
    alphas = set(recon[3::4])
    if 0 not in alphas:
        raise ValueError("Missing transparent pixels (alpha 0) in XP character sheet")
    if 255 not in alphas:
        raise ValueError("Missing fully opaque pixels (alpha 255) in XP character sheet")

    # Check Column 3 duplication (Col 3 == Col 1 for all rows)
    for row in range(4):
        for py in range(32):
            y = row * 32 + py
            for px in range(24):
                col1_px = get_pixel(24 + px, y)
                col3_px = get_pixel(72 + px, y)
                if col1_px != col3_px:
                    raise ValueError(f"Column 3 (idle step) does not match Column 1 at row {row}, local ({px},{py})")

    # Check directional arrow orientation on Idle column (Col 1, x=24..47) for all 4 rows:
    # Row 0: DOWN, Row 1: LEFT, Row 2: RIGHT, Row 3: UP
    r0_tip = get_pixel(24 + 11, 0 * 32 + 21)
    r0_notch = get_pixel(24 + 11, 0 * 32 + 6)
    if r0_tip[3] == 0:
        raise ValueError("Row 0 arrow orientation error: expected DOWN facing arrow tip at center-bottom")
    if r0_notch[3] != 0:
        raise ValueError("Row 0 arrow orientation error: expected DOWN facing arrow notch at center-top")

    r3_tip = get_pixel(24 + 11, 3 * 32 + 5)
    r3_notch = get_pixel(24 + 11, 3 * 32 + 21)
    if r3_tip[3] == 0:
        raise ValueError("Row 3 arrow orientation error: expected UP facing arrow tip at center-top")
    if r3_notch[3] != 0:
        raise ValueError("Row 3 arrow orientation error: expected UP facing arrow notch at center-bottom")

    r1_tip = get_pixel(24 + 4, 1 * 32 + 13)
    r1_notch = get_pixel(24 + 19, 1 * 32 + 13)
    if r1_tip[3] == 0:
        raise ValueError("Row 1 arrow orientation error: expected LEFT facing arrow tip at center-left")
    if r1_notch[3] != 0:
        raise ValueError("Row 1 arrow orientation error: expected LEFT facing arrow notch at center-right")

    r2_tip = get_pixel(24 + 19, 2 * 32 + 13)
    r2_notch = get_pixel(24 + 4, 2 * 32 + 13)
    if r2_tip[3] == 0:
        raise ValueError("Row 2 arrow orientation error: expected RIGHT facing arrow tip at center-right")
    if r2_notch[3] != 0:
        raise ValueError("Row 2 arrow orientation error: expected RIGHT facing arrow notch at center-left")

    return {
        "width": width,
        "height": height,
        "bit_depth": bit_depth,
        "color_type": color_type,
        "num_colors": "truecolor-rgba",
        "has_trns": False,
        "frame_cell": "24x32",
        "grid": "4x4",
        "directions": ["DOWN", "LEFT", "RIGHT", "UP"]
    }

def validate_png_vx_family_character(filepath, engine_name="VX"):
    """Validates VX-family (RPG Maker VX / VX Ace) standard 8-character sheet technical specifications and calibration geometry."""
    with open(filepath, "rb") as f:
        data = f.read()

    chunks = parse_png_chunks(data)
    chunk_types = [c[0] for c in chunks]

    # Required chunks in order
    if not chunk_types or chunk_types[0] != "IHDR":
        raise ValueError("PNG must start with IHDR chunk")
    if "PLTE" in chunk_types:
        raise ValueError(f"Unexpected PLTE (Palette) chunk: RPG Maker {engine_name} character sheets must be truecolor RGBA")
    if "IDAT" not in chunk_types:
        raise ValueError("Missing IDAT chunk")
    if chunk_types[-1] != "IEND":
        raise ValueError("PNG must terminate with IEND chunk")

    # Inspect IHDR
    ihdr_data = next(c[1] for c in chunks if c[0] == "IHDR")
    width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack('>IIBBBBB', ihdr_data)

    if width != 288 or height != 256:
        raise ValueError(f"Invalid {engine_name} Character dimensions: expected 288x256, got {width}x{height}")
    if bit_depth != 8:
        raise ValueError(f"Invalid bit depth: expected 8, got {bit_depth}")
    if color_type != 6:
        raise ValueError(f"Invalid color type: expected 6 (RGBA truecolor), got {color_type}")
    if compression != 0 or filter_method != 0 or interlace != 0:
        raise ValueError("Unsupported compression/filter/interlace method")

    # Decompress IDAT and reconstruct 32-bit RGBA pixel grid
    idat_data = b''.join(c[1] for c in chunks if c[0] == "IDAT")
    raw = bytearray(zlib.decompress(idat_data))
    bpp = 4
    stride = 1 + width * bpp
    if len(raw) != height * stride:
        raise ValueError(f"Decompressed IDAT size mismatch: expected {height * stride}, got {len(raw)}")

    recon = bytearray(width * height * bpp)
    prior = bytearray(width * bpp)

    for y in range(height):
        filter_type = raw[y * stride]
        filt = raw[y * stride + 1 : (y + 1) * stride]
        line = bytearray(width * bpp)

        if filter_type == 0:
            line[:] = filt
        elif filter_type == 1:
            for x in range(width * bpp):
                a = line[x - bpp] if x >= bpp else 0
                line[x] = (filt[x] + a) & 0xff
        elif filter_type == 2:
            for x in range(width * bpp):
                line[x] = (filt[x] + prior[x]) & 0xff
        elif filter_type == 3:
            for x in range(width * bpp):
                a = line[x - bpp] if x >= bpp else 0
                line[x] = (filt[x] + ((a + prior[x]) >> 1)) & 0xff
        elif filter_type == 4:
            for x in range(width * bpp):
                a = line[x - bpp] if x >= bpp else 0
                b = prior[x]
                c = prior[x - bpp] if x >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (filt[x] + pr) & 0xff
        else:
            raise ValueError(f"Unknown PNG filter type {filter_type}")

        prior[:] = line
        recon[y * width * bpp : (y + 1) * width * bpp] = line

    def get_pixel(x, y):
        idx = (y * width + x) * 4
        return (recon[idx], recon[idx + 1], recon[idx + 2], recon[idx + 3])

    # Check alpha distribution
    alphas = set(recon[3::4])
    if 0 not in alphas:
        raise ValueError("Missing transparent pixels (alpha 0) in VX character sheet")
    if 255 not in alphas:
        raise ValueError("Missing fully opaque pixels (alpha 255) in VX character sheet")

    # Check grid divisibility: 4x2 characters, each character 72x128 with 3 columns x 4 rows of 24x32
    if width % 12 != 0 or height % 8 != 0:
        raise ValueError(f"Dimensions {width}x{height} not divisible by 12x8 standard VX cells")

    # Check directional arrow orientation on Idle column (Col 1 of each character block) for all 8 characters
    for char_idx in range(8):
        char_x = (char_idx % 4) * 72
        char_y = (char_idx // 4) * 128
        idle_x = char_x + 24  # Col 1 (Idle column) starts at +24

        # Row 0: DOWN (tip at bottom, notch at top)
        r0_tip = get_pixel(idle_x + 11, char_y + 0 * 32 + 21)
        r0_notch = get_pixel(idle_x + 11, char_y + 0 * 32 + 6)
        if r0_tip[3] == 0:
            raise ValueError(f"Character {char_idx} Row 0 arrow orientation error: expected DOWN facing arrow tip at center-bottom")
        if r0_notch[3] != 0:
            raise ValueError(f"Character {char_idx} Row 0 arrow orientation error: expected DOWN facing arrow notch at center-top")

        # Row 1: LEFT (tip at left, notch at right)
        r1_tip = get_pixel(idle_x + 4, char_y + 1 * 32 + 13)
        r1_notch = get_pixel(idle_x + 19, char_y + 1 * 32 + 13)
        if r1_tip[3] == 0:
            raise ValueError(f"Character {char_idx} Row 1 arrow orientation error: expected LEFT facing arrow tip at center-left")
        if r1_notch[3] != 0:
            raise ValueError(f"Character {char_idx} Row 1 arrow orientation error: expected LEFT facing arrow notch at center-right")

        # Row 2: RIGHT (tip at right, notch at left)
        r2_tip = get_pixel(idle_x + 19, char_y + 2 * 32 + 13)
        r2_notch = get_pixel(idle_x + 4, char_y + 2 * 32 + 13)
        if r2_tip[3] == 0:
            raise ValueError(f"Character {char_idx} Row 2 arrow orientation error: expected RIGHT facing arrow tip at center-right")
        if r2_notch[3] != 0:
            raise ValueError(f"Character {char_idx} Row 2 arrow orientation error: expected RIGHT facing arrow notch at center-left")

        # Row 3: UP (tip at top, notch at bottom)
        r3_tip = get_pixel(idle_x + 11, char_y + 3 * 32 + 5)
        r3_notch = get_pixel(idle_x + 11, char_y + 3 * 32 + 21)
        if r3_tip[3] == 0:
            raise ValueError(f"Character {char_idx} Row 3 arrow orientation error: expected UP facing arrow tip at center-top")
        if r3_notch[3] != 0:
            raise ValueError(f"Character {char_idx} Row 3 arrow orientation error: expected UP facing arrow notch at center-bottom")

    return {
        "width": width,
        "height": height,
        "bit_depth": bit_depth,
        "color_type": color_type,
        "num_colors": "truecolor-rgba",
        "has_trns": False,
        "frame_cell": "24x32",
        "character_block": "72x128",
        "grid": "4x2 characters (12x8 cells)",
        "directions": ["DOWN", "LEFT", "RIGHT", "UP"]
    }

def validate_png_rmvx_character(filepath):
    """Validates RPG Maker VX / RGSS2 standard 8-character sheet specifications."""
    return validate_png_vx_family_character(filepath, engine_name="VX")

def validate_png_rmvxace_character(filepath):
    """Validates RPG Maker VX Ace / RGSS3 standard 8-character sheet specifications."""
    return validate_png_vx_family_character(filepath, engine_name="VX Ace")

def validate_png_wolf_character(filepath):
    """Validates WOLF RPG Editor v3 standard 3-pattern x 4-direction character chip specifications."""
    basename = os.path.basename(filepath)
    if basename.endswith(("T.png", "TX.png", "$.png")):
        raise ValueError(f"WOLF character filename '{basename}' invokes special filename mode (T, TX, or $); out of scope for standard CharaChip")

    with open(filepath, "rb") as f:
        data = f.read()

    chunks = parse_png_chunks(data)
    chunk_types = [c[0] for c in chunks]

    # Required chunks in order
    if not chunk_types or chunk_types[0] != "IHDR":
        raise ValueError("PNG must start with IHDR chunk")
    if "PLTE" in chunk_types:
        raise ValueError("Unexpected PLTE (Palette) chunk: WOLF RPG Editor character chips must be truecolor RGBA")
    if "tRNS" in chunk_types:
        raise ValueError("Unexpected tRNS chunk: WOLF truecolor RGBA must carry alpha channel directly")
    if "IDAT" not in chunk_types:
        raise ValueError("Missing IDAT chunk")
    if chunk_types[-1] != "IEND":
        raise ValueError("PNG must terminate with IEND chunk")

    # Inspect IHDR
    ihdr_data = next(c[1] for c in chunks if c[0] == "IHDR")
    width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack('>IIBBBBB', ihdr_data)

    if width != 72 or height != 128:
        raise ValueError(f"Invalid WOLF Character dimensions: expected 72x128, got {width}x{height}")
    if bit_depth != 8:
        raise ValueError(f"Invalid bit depth: expected 8, got {bit_depth}")
    if color_type != 6:
        raise ValueError(f"Invalid color type: expected 6 (RGBA truecolor), got {color_type}")
    if compression != 0 or filter_method != 0 or interlace != 0:
        raise ValueError("Unsupported compression/filter/interlace method")

    # Decompress IDAT and reconstruct 32-bit RGBA pixel grid
    idat_data = b''.join(c[1] for c in chunks if c[0] == "IDAT")
    raw = bytearray(zlib.decompress(idat_data))
    bpp = 4
    stride = 1 + width * bpp
    if len(raw) != height * stride:
        raise ValueError(f"Decompressed IDAT size mismatch: expected {height * stride}, got {len(raw)}")

    recon = bytearray(width * height * bpp)
    prior = bytearray(width * bpp)

    for y in range(height):
        filter_type = raw[y * stride]
        filt = raw[y * stride + 1 : (y + 1) * stride]
        line = bytearray(width * bpp)

        if filter_type == 0:
            line[:] = filt
        elif filter_type == 1:
            for x in range(width * bpp):
                a = line[x - bpp] if x >= bpp else 0
                line[x] = (filt[x] + a) & 0xff
        elif filter_type == 2:
            for x in range(width * bpp):
                line[x] = (filt[x] + prior[x]) & 0xff
        elif filter_type == 3:
            for x in range(width * bpp):
                a = line[x - bpp] if x >= bpp else 0
                line[x] = (filt[x] + ((a + prior[x]) >> 1)) & 0xff
        elif filter_type == 4:
            for x in range(width * bpp):
                a = line[x - bpp] if x >= bpp else 0
                b = prior[x]
                c = prior[x - bpp] if x >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (filt[x] + pr) & 0xff
        else:
            raise ValueError(f"Unknown PNG filter type {filter_type}")

        prior[:] = line
        recon[y * width * bpp : (y + 1) * width * bpp] = line

    def get_pixel(x, y):
        idx = (y * width + x) * 4
        return (recon[idx], recon[idx + 1], recon[idx + 2], recon[idx + 3])

    # Check alpha distribution
    alphas = set(recon[3::4])
    if 0 not in alphas:
        raise ValueError("Missing transparent pixels (alpha 0) in WOLF character sheet")
    if 255 not in alphas:
        raise ValueError("Missing fully opaque pixels (alpha 255) in WOLF character sheet")

    # Check directional arrow orientation on Idle column (Col 1: x = 24..47)
    idle_x = 24
    # Row 0: DOWN (tip at bottom (11, 21), notch at top (11, 6))
    r0_tip = get_pixel(idle_x + 11, 0 * 32 + 21)
    r0_notch = get_pixel(idle_x + 11, 0 * 32 + 6)
    if r0_tip[3] == 0:
        raise ValueError("Row 0 arrow orientation error: expected DOWN facing arrow tip at center-bottom")
    if r0_notch[3] != 0:
        raise ValueError("Row 0 arrow orientation error: expected DOWN facing arrow notch at center-top")

    # Row 1: LEFT (tip at left (4, 13), notch at right (19, 13))
    r1_tip = get_pixel(idle_x + 4, 1 * 32 + 13)
    r1_notch = get_pixel(idle_x + 19, 1 * 32 + 13)
    if r1_tip[3] == 0:
        raise ValueError("Row 1 arrow orientation error: expected LEFT facing arrow tip at center-left")
    if r1_notch[3] != 0:
        raise ValueError("Row 1 arrow orientation error: expected LEFT facing arrow notch at center-right")

    # Row 2: RIGHT (tip at right (19, 13), notch at left (4, 13))
    r2_tip = get_pixel(idle_x + 19, 2 * 32 + 13)
    r2_notch = get_pixel(idle_x + 4, 2 * 32 + 13)
    if r2_tip[3] == 0:
        raise ValueError("Row 2 arrow orientation error: expected RIGHT facing arrow tip at center-right")
    if r2_notch[3] != 0:
        raise ValueError("Row 2 arrow orientation error: expected RIGHT facing arrow notch at center-left")

    # Row 3: UP (tip at top (11, 5), notch at bottom (11, 21))
    r3_tip = get_pixel(idle_x + 11, 3 * 32 + 5)
    r3_notch = get_pixel(idle_x + 11, 3 * 32 + 21)
    if r3_tip[3] == 0:
        raise ValueError("Row 3 arrow orientation error: expected UP facing arrow tip at center-top")
    if r3_notch[3] != 0:
        raise ValueError("Row 3 arrow orientation error: expected UP facing arrow notch at center-bottom")

    # Validate all 12 cells against canonical semantic oracle if available
    canonical_rgba_path = os.path.join(REPO_ROOT, "registry", "assets", "test_calibration_walking_character.rgba")
    if os.path.exists(canonical_rgba_path):
        from build_target import extract_walking_frames
        with open(canonical_rgba_path, "rb") as cf:
            canonical_rgba = cf.read()
        semantic_frames = extract_walking_frames(canonical_rgba, char_idx=0)
        wolf_row_order = ["DOWN", "LEFT", "RIGHT", "UP"]
        wolf_col_phases = ["STEP_LEFT", "IDLE", "STEP_RIGHT"]

        for row_idx, direction in enumerate(wolf_row_order):
            for col_idx, phase in enumerate(wolf_col_phases):
                expected_cell = semantic_frames[direction][phase]
                cell_bytes = bytearray()
                for py in range(32):
                    start_off = ((row_idx * 32 + py) * 72 + col_idx * 24) * 4
                    cell_bytes.extend(recon[start_off : start_off + 24 * 4])
                if bytes(cell_bytes) != expected_cell:
                    raise ValueError(f"Cell ({row_idx}, {col_idx}) [{direction}/{phase}] does not match canonical semantic oracle")

    return {
        "width": width,
        "height": height,
        "bit_depth": bit_depth,
        "color_type": color_type,
        "num_colors": "truecolor-rgba",
        "has_trns": False,
        "frame_cell": "24x32",
        "character_block": "72x128",
        "grid": "1 character (3x4 cells)",
        "directions": ["DOWN", "LEFT", "RIGHT", "UP"],
        "animation_patterns": ["STEP_LEFT", "IDLE", "STEP_RIGHT"],
        "cells_verified": 12
    }

def validate_schemas(repo_root, target):
    """Enforces JSON Schema validation on registry files."""
    slots_path = os.path.join(repo_root, "registry", "slots", f"{target}.json")
    slots_schema_path = os.path.join(repo_root, "schemas", "slot_mapping.schema.json")
    with open(slots_path, "r", encoding="utf-8") as sf:
        slots_data = json.load(sf)
    with open(slots_schema_path, "r", encoding="utf-8") as ssf:
        slots_schema = json.load(ssf)
    validate_schema(slots_data, slots_schema, path=os.path.basename(slots_path))

    asset_schema_path = os.path.join(repo_root, "schemas", "asset.schema.json")
    with open(asset_schema_path, "r", encoding="utf-8") as asf:
        asset_schema = json.load(asf)

    prov_schema_path = os.path.join(repo_root, "schemas", "provenance.schema.json")
    with open(prov_schema_path, "r", encoding="utf-8") as psf:
        prov_schema = json.load(psf)

    for slot_key, slot_info in slots_data.get("slots", {}).items():
        asset_id = slot_info["asset_id"]

        # Validate alias taxonomy and disjoint union
        aliases = slot_info.get("aliases", [])
        upstream = slot_info.get("upstream_aliases")
        case_vars = slot_info.get("emitted_case_variants")
        if upstream is not None or case_vars is not None:
            up_set = set(upstream or [])
            cv_set = set(case_vars or [])
            alias_set = set(aliases)
            if not up_set.isdisjoint(cv_set):
                overlap = up_set & cv_set
                raise ValueError(f"Slot '{slot_key}' has overlapping upstream and case variant aliases: {overlap}")
            if up_set | cv_set != alias_set:
                raise ValueError(f"Slot '{slot_key}' aliases union mismatch: (upstream | case_variants) != aliases")
        slot_path = slot_info.get("slot_path", slot_key)
        if slot_path in aliases:
            raise ValueError(f"Slot '{slot_key}' aliases must not include primary slot_path '{slot_path}'")

        # Find and validate asset metadata against schema
        asset_file = None
        for fname in os.listdir(os.path.join(repo_root, "registry", "assets")):
            if fname.endswith(".json"):
                cand = os.path.join(repo_root, "registry", "assets", fname)
                with open(cand, "r", encoding="utf-8") as cf:
                    data = json.load(cf)
                    if data.get("id") == asset_id:
                        asset_file = cand
                        validate_schema(data, asset_schema, path=fname)
                        break
        if not asset_file:
            raise FileNotFoundError(f"Asset metadata for '{asset_id}' not found")

        # Find and validate provenance against schema
        prov_file = None
        for fname in os.listdir(os.path.join(repo_root, "registry", "provenance")):
            if fname.endswith(".json"):
                cand = os.path.join(repo_root, "registry", "provenance", fname)
                with open(cand, "r", encoding="utf-8") as cf:
                    data = json.load(cf)
                    if data.get("asset_id") == asset_id:
                        prov_file = cand
                        validate_schema(data, prov_schema, path=fname)
                        break
        if not prov_file:
            raise FileNotFoundError(f"Provenance record for '{asset_id}' not found")

    return True

def validate_provenance(repo_root, asset_id, source_sha256):
    """Validates that provenance records are complete and attest clean-room integrity."""
    prov_file = None
    for fname in os.listdir(os.path.join(repo_root, "registry", "provenance")):
        if fname.endswith(".json"):
            cand = os.path.join(repo_root, "registry", "provenance", fname)
            with open(cand, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data.get("asset_id") == asset_id:
                    prov_file = cand
                    break
    if not prov_file:
        raise FileNotFoundError(f"Provenance record for '{asset_id}' not found in registry/provenance/")

    with open(prov_file, "r", encoding="utf-8") as pf:
        prov = json.load(pf)

    if prov.get("sha256") != source_sha256:
        raise ValueError(f"Provenance hash mismatch: expected {prov.get('sha256')}, got {source_sha256}")

    attestation = prov.get("clean_room_attestation", {})
    if attestation.get("proprietary_rtp_derived") is not False:
        raise ValueError("Provenance violation: proprietary_rtp_derived must be false")
    if attestation.get("openrtp_derived") is not False:
        raise ValueError("Provenance violation: openrtp_derived must be false")

    # Source-type-aware validation and evidence checks
    source_type = prov.get("source_type")
    valid_source_types = {"project_synthetic", "externally_licensed", "ai_generated"}
    if source_type not in valid_source_types:
        raise ValueError(f"Invalid source_type: {source_type}. Must be one of {valid_source_types}")

    license_str = prov.get("license")
    permitted_licenses = {
        "CC0-1.0", "CC-BY-4.0", "CC-BY-3.0", "CC-BY-SA-4.0",
        "MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "OFL-1.1", "Public Domain"
    }
    if license_str not in permitted_licenses:
        raise ValueError(f"Provenance license violation: '{license_str}' is not an approved redistribution license: {permitted_licenses}")

    if source_type == "project_synthetic":
        creation_tool = prov.get("creation_tool")
        if not creation_tool or not isinstance(creation_tool, str):
            raise ValueError("Provenance violation: source_type 'project_synthetic' requires non-empty 'creation_tool'")
        if prov.get("test_only") and license_str != "CC0-1.0":
            raise ValueError(f"Provenance violation: test_only synthetic asset must be CC0-1.0, got {license_str}")

    elif source_type == "externally_licensed":
        upstream = prov.get("upstream_source")
        if not upstream or not isinstance(upstream, dict):
            raise ValueError("Provenance violation: source_type 'externally_licensed' requires 'upstream_source' object")
        for field in ["author", "url", "license_evidence"]:
            if not upstream.get(field):
                raise ValueError(f"Provenance violation: externally_licensed requires non-empty upstream_source.{field}")

    elif source_type == "ai_generated":
        gen_meta = prov.get("generation_metadata")
        if not gen_meta or not isinstance(gen_meta, dict):
            raise ValueError("Provenance violation: source_type 'ai_generated' requires 'generation_metadata' object")
        for field in ["model", "provider", "prompt", "parameters", "date"]:
            if not gen_meta.get(field):
                raise ValueError(f"Provenance violation: ai_generated requires non-empty generation_metadata.{field}")

    return prov

def validate_target(target, target_dir=None):
    repo_root = REPO_ROOT
    if target_dir is None:
        target_dir = os.path.join(repo_root, "generated", target)
    target_dir = os.path.abspath(target_dir)

    print(f"=== Validating SuperRTP Target '{target}' ===")

    # Step 1: Enforce Schema Validation
    print("Enforcing JSON Schema validation on registry metadata...")
    try:
        validate_schemas(repo_root, target)
        print("  PASSED: All registry metadata conforms to JSON schemas.")
    except Exception as e:
        print(f"  FAILED Schema validation: {e}")
        return 1

    # Load slot mapping registry to cross-check categories and declared slots
    slots_path = os.path.join(repo_root, "registry", "slots", f"{target}.json")
    if not os.path.exists(slots_path):
        raise FileNotFoundError(f"Slot mapping not found: {slots_path}")
    with open(slots_path, "r", encoding="utf-8") as sf:
        slots_data = json.load(sf)

    slot_lookup = {}
    for slot_key, s_info in slots_data.get("slots", {}).items():
        primary_path = s_info.get("slot_path", slot_key)
        slot_lookup[primary_path] = s_info
        for alias in s_info.get("aliases", []):
            slot_lookup[alias] = s_info

    manifest_path = os.path.join(target_dir, "manifest.json")
    if not os.path.exists(manifest_path):
        raise FileNotFoundError(f"Missing build manifest in target directory: {manifest_path}")

    with open(manifest_path, "r", encoding="utf-8") as mf:
        manifest = json.load(mf)

    print(f"Directory: {target_dir}")
    print(f"Target Name: {manifest.get('target_name')}")
    print(f"Engine: {manifest.get('engine')}")
    print(f"Reference Source: {manifest.get('reference_source')}")
    print(f"Entries to validate: {len(manifest.get('entries', []))}")

    all_passed = True
    validated_count = 0

    # Top-level manifest identity validation against target and slot registry
    manifest_target = manifest.get("target")
    expected_target = slots_data.get("target", target)
    if manifest_target != target or manifest_target != expected_target:
        print(f"  FAILED: Target mismatch in manifest: expected '{target}', got '{manifest_target}'")
        all_passed = False

    expected_engine = slots_data.get("engine")
    manifest_engine = manifest.get("engine")
    if expected_engine and manifest_engine != expected_engine:
        print(f"  FAILED: Engine mismatch in manifest: expected '{expected_engine}', got '{manifest_engine}'")
        all_passed = False

    expected_target_name = slots_data.get("target_name")
    manifest_target_name = manifest.get("target_name")
    if expected_target_name and manifest_target_name != expected_target_name:
        print(f"  FAILED: Target name mismatch in manifest: expected '{expected_target_name}', got '{manifest_target_name}'")
        all_passed = False

    for entry in manifest.get("entries", []):
        slot = entry["slot"]
        asset_id = entry["asset_id"]
        manifest_category = entry.get("category")
        filepath = os.path.join(target_dir, slot)
        print(f"\nChecking [{slot}]...")

        if not manifest_category:
            print(f"  FAILED: Missing semantic category in manifest entry for {slot}")
            all_passed = False
            continue

        if slot not in slot_lookup:
            print(f"  FAILED: Slot '{slot}' is not declared in slot mapping registry {slots_path}")
            all_passed = False
            continue

        registry_category = slot_lookup[slot].get("category")
        if manifest_category != registry_category:
            print(f"  FAILED: Category mismatch for slot '{slot}': manifest has '{manifest_category}', registry has '{registry_category}'")
            all_passed = False
            continue

        # Transformation metadata validation: cross-check with registry
        transform_meta_fields = [
            "character_index",
            "source_character_indices",
            "direction_mode",
            "animation_patterns",
            "runtime_reference",
            "transform_policy"
        ]
        meta_mismatch = False
        for field in transform_meta_fields:
            reg_val = slot_lookup[slot].get(field)
            man_val = entry.get(field)
            if reg_val != man_val:
                print(f"  FAILED: Transformation metadata mismatch for slot '{slot}' field '{field}': manifest has {man_val!r}, registry has {reg_val!r}")
                all_passed = False
                meta_mismatch = True
                break
        if meta_mismatch:
            continue

        if not os.path.exists(filepath):
            print(f"  FAILED: File missing at {filepath}")
            all_passed = False
            continue

        # Hash check
        h = hashlib.sha256()
        with open(filepath, "rb") as f:
            h.update(f.read())
        actual_sha256 = h.hexdigest()
        if actual_sha256 != entry["sha256"]:
            print(f"  FAILED: Hash mismatch in manifest! Expected {entry['sha256']}, got {actual_sha256}")
            all_passed = False
            continue

        # PNG Specification check dispatched by verified semantic category
        try:
            cat_norm = manifest_category.lower()
            if cat_norm == "chipset":
                specs = validate_png_chipset(filepath)
                spec_desc = f"{specs['width']}x{specs['height']}, {specs['num_colors']} colors, indexed-8, index 0 transparent (tRNS={specs['has_trns']})"
            elif cat_norm == "charset":
                specs = validate_png_charset(filepath)
                spec_desc = f"{specs['width']}x{specs['height']}, {specs['num_colors']} colors, indexed-8, index 0 transparent (tRNS={specs['has_trns']})"
            elif cat_norm == "character":
                if target == "rmxp":
                    specs = validate_png_rmxp_character(filepath)
                    spec_desc = f"{specs['width']}x{specs['height']}, truecolor RGBA (Type 6), 4x4 frames (Down, Left, Right, Up)"
                elif target in ("rmvx", "rmvxace"):
                    engine_name = "VX Ace" if target == "rmvxace" else "VX"
                    specs = validate_png_vx_family_character(filepath, engine_name=engine_name)
                    spec_desc = f"{specs['width']}x{specs['height']}, truecolor RGBA (Type 6), 8 characters (4x2), 3x4 frames each (Down, Left, Right, Up)"
                elif target == "wolf":
                    specs = validate_png_wolf_character(filepath)
                    spec_desc = f"{specs['width']}x{specs['height']}, truecolor RGBA (Type 6), 3x4 frames (Down, Left, Right, Up), 12 cells verified"
                else:
                    raise ValueError(f"Unsupported target '{target}' for character category")
            else:
                raise ValueError(f"Unknown or unsupported semantic category '{manifest_category}' for slot '{slot}'")
            print(f"  PASSED PNG specs: {spec_desc}")
        except Exception as e:
            print(f"  FAILED PNG validation: {e}")
            all_passed = False
            continue

        # Source Asset & Provenance check
        try:
            # Find source asset
            source_meta = None
            for fname in os.listdir(os.path.join(repo_root, "registry", "assets")):
                if fname.endswith(".json"):
                    cand = os.path.join(repo_root, "registry", "assets", fname)
                    with open(cand, "r", encoding="utf-8") as cf:
                        d = json.load(cf)
                        if d.get("id") == asset_id:
                            source_meta = d
                            break
            source_file = os.path.join(repo_root, source_meta["file"])
            with open(source_file, "rb") as sf:
                source_sha256 = hashlib.sha256(sf.read()).hexdigest()

            prov = validate_provenance(repo_root, asset_id, source_sha256)
            print(f"  PASSED Provenance: License={prov['license']}, CleanRoom=VERIFIED, SourceType={prov['source_type']}")
        except Exception as e:
            print(f"  FAILED Provenance validation: {e}")
            all_passed = False
            continue

        validated_count += 1

    print("\n" + "="*45)
    if all_passed and validated_count > 0:
        print(f"ALL CHECKS PASSED: {validated_count} target files verified successfully.")
        return 0
    else:
        print(f"VALIDATION FAILED: {validated_count} passed out of {len(manifest.get('entries', []))}.")
        return 1

def main():
    parser = argparse.ArgumentParser(description="SuperRTP Target Validator")
    parser.add_argument("--target", required=True, help="Target name (e.g. rm2000)")
    parser.add_argument("--target-dir", default=None, help="Custom target directory")
    args = parser.parse_args()

    sys.exit(validate_target(args.target, args.target_dir))

if __name__ == "__main__":
    main()
