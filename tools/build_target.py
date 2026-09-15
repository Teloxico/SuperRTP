#!/usr/bin/env python3
"""
Deterministic Target Builder for SuperRTP.

Performs target-specific transformation from neutral canonical assets into
engine-compliant runtime packages:
  canonical source (neutral RGBA)
    -> provenance verification
    -> slot mapping
    -> target transformation (exact palette extraction and indexing, index-0 transparency, chunk encoding)
    -> target output (generated/<target>/)
    -> reproducible manifest

Usage:
  python3 tools/build_target.py --target rm2000 [--output-dir generated/rm2000] [--clean]
"""

import os
import sys
import json
import struct
import zlib
import hashlib
import argparse
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from png_utils import deterministic_zlib_compress, make_png_chunk, create_rgba_png

def compute_sha256(filepath):
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def create_indexed_png(width, height, palette, pixel_indices, has_trns=True):
    """
    Low-level encoder for standard 8-bit indexed PNG with optional tRNS chunk using deterministic compression.
    """
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

def transform_rgba_to_indexed_png(rgba_bytes, width=288, height=256):
    """
    Transforms neutral 32-bit RGBA pixels into 2k-family compliant 8-bit indexed PNG (RM2000/RM2003).
    - Deterministically builds a <= 256 color palette.
    - Guarantees palette index 0 is transparent (RGB 0,0,0, alpha 0).
    - Encodes IHDR (type 3), PLTE, tRNS, IDAT, and IEND chunks.
    """
    if len(rgba_bytes) != width * height * 4:
        raise ValueError(f"Input RGBA buffer size mismatch: expected {width*height*4}, got {len(rgba_bytes)}")

    # Deterministic palette extraction
    # Index 0 is always transparent
    palette = [(0, 0, 0)]
    color_to_index = {}

    pixel_indices = bytearray(width * height)

    for i in range(width * height):
        offset = i * 4
        r = rgba_bytes[offset]
        g = rgba_bytes[offset + 1]
        b = rgba_bytes[offset + 2]
        a = rgba_bytes[offset + 3]

        if a == 0:
            # Transparent pixel -> index 0
            pixel_indices[i] = 0
        else:
            rgb = (r, g, b)
            if rgb not in color_to_index:
                if len(palette) >= 256:
                    raise ValueError(f"Asset exceeds RM2000 256-color limit: {len(palette)} unique colors")
                idx = len(palette)
                palette.append(rgb)
                color_to_index[rgb] = idx
            pixel_indices[i] = color_to_index[rgb]

    return create_indexed_png(width, height, palette, pixel_indices, has_trns=True)
 
transform_rgba_to_rm2000_indexed_png = transform_rgba_to_indexed_png
 
def extract_walking_frames(
    source_rgba_bytes: bytes,
    char_idx: int = 0,
    frame_w: int = 24,
    frame_h: int = 32,
    sheet_w: int = 288,
    sheet_h: int = 256
) -> dict:
    """
    Extracts semantic walking frames for a single character from a 2k-family canonical sheet.

    Returns a nested dict:
      frames[direction][phase] -> bytes (frame_w * frame_h * 4 RGBA bytes)
    where:
      direction in ("UP", "RIGHT", "DOWN", "LEFT")
      phase in ("STEP_LEFT", "IDLE", "STEP_RIGHT")

    Canonical 2k layout geometry:
      - 8 characters in 4x2 grid (72x128 px per character)
      - Row order: 0: UP, 1: RIGHT, 2: DOWN, 3: LEFT
      - Column order: 0: STEP_LEFT, 1: IDLE, 2: STEP_RIGHT
    """
    expected_len = sheet_w * sheet_h * 4
    if len(source_rgba_bytes) != expected_len:
        raise ValueError(f"Input RGBA buffer size mismatch: expected {expected_len}, got {len(source_rgba_bytes)}")
    if not (0 <= char_idx < 8):
        raise ValueError(f"Character index out of range (0..7): {char_idx}")

    char_grid_x = char_idx % 4
    char_grid_y = char_idx // 4
    char_base_x = char_grid_x * (3 * frame_w)
    char_base_y = char_grid_y * (4 * frame_h)

    directions = ["UP", "RIGHT", "DOWN", "LEFT"]
    phases = ["STEP_LEFT", "IDLE", "STEP_RIGHT"]

    frames = {d: {} for d in directions}

    for row_idx, direction in enumerate(directions):
        for col_idx, phase in enumerate(phases):
            src_frame_x = char_base_x + col_idx * frame_w
            src_frame_y = char_base_y + row_idx * frame_h
            frame_bytes = bytearray(frame_w * frame_h * 4)

            for py in range(frame_h):
                src_y = src_frame_y + py
                dst_y = py
                src_row_start = (src_y * sheet_w + src_frame_x) * 4
                src_row_end = src_row_start + frame_w * 4
                dst_row_start = (dst_y * frame_w) * 4
                dst_row_end = dst_row_start + frame_w * 4
                frame_bytes[dst_row_start:dst_row_end] = source_rgba_bytes[src_row_start:src_row_end]

            frames[direction][phase] = bytes(frame_bytes)

    return frames

def pack_rmxp_character(semantic_frames: dict, frame_w: int = 24, frame_h: int = 32) -> bytes:
    """
    Packs semantic walking frames into an RPG Maker XP / RGSS1 compliant 4x4 sheet.

    Input:
      semantic_frames: dict[direction, dict[phase, bytes]]

    Target layout policy (RPG Maker XP / RGSS1):
      - 4 rows (directions): DOWN, LEFT, RIGHT, UP
      - 4 columns (phases): STEP_LEFT, IDLE, STEP_RIGHT, IDLE (4-phase walk cycle with repeated idle)
      - Sheet size: (4 * frame_w) x (4 * frame_h) = 96 x 128 px
      - Output: 32-bit truecolor RGBA PNG (Color Type 6) with deterministic RFC 1951 stored blocks.
    """
    dst_width = 4 * frame_w
    dst_height = 4 * frame_h
    dst_rgba = bytearray(dst_width * dst_height * 4)

    xp_row_order = ["DOWN", "LEFT", "RIGHT", "UP"]
    xp_col_phases = ["STEP_LEFT", "IDLE", "STEP_RIGHT", "IDLE"]

    for row_idx, direction in enumerate(xp_row_order):
        if direction not in semantic_frames:
            raise KeyError(f"Missing required direction in semantic frames: {direction}")
        for col_idx, phase in enumerate(xp_col_phases):
            if phase not in semantic_frames[direction]:
                raise KeyError(f"Missing required phase '{phase}' for direction '{direction}'")
            frame_raw = semantic_frames[direction][phase]
            expected_frame_len = frame_w * frame_h * 4
            if len(frame_raw) != expected_frame_len:
                raise ValueError(f"Frame length mismatch for {direction}/{phase}: expected {expected_frame_len}, got {len(frame_raw)}")

            dst_frame_x = col_idx * frame_w
            dst_frame_y = row_idx * frame_h

            for py in range(frame_h):
                src_offset = py * frame_w * 4
                dst_offset = ((dst_frame_y + py) * dst_width + dst_frame_x) * 4
                dst_rgba[dst_offset : dst_offset + frame_w * 4] = frame_raw[src_offset : src_offset + frame_w * 4]

    return create_rgba_png(dst_width, dst_height, bytes(dst_rgba))

def transform_canonical_to_rmxp_character(source_bytes: bytes, char_idx: int = 0) -> bytes:
    """
    Transforms neutral 32-bit RGBA canonical 2k-family walking character sheet (288x256)
    into an RPG Maker XP / RGSS1 compliant 32-bit truecolor RGBA Character sheet (96x128).

    Decoupled pipeline:
      Canonical 2k sheet -> extract_walking_frames() -> Semantic Frames (UP/RIGHT/DOWN/LEFT, STEP_LEFT/IDLE/STEP_RIGHT)
      Semantic Frames -> pack_rmxp_character() -> XP 4x4 RGBA PNG
    """
    semantic_frames = extract_walking_frames(source_bytes, char_idx=char_idx)
    return pack_rmxp_character(semantic_frames)

def get_reproducible_timestamp():
    """Returns a deterministic ISO-8601 timestamp based on SOURCE_DATE_EPOCH if set."""
    sde = os.environ.get("SOURCE_DATE_EPOCH")
    if sde:
        try:
            epoch = int(sde)
            return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()
        except ValueError:
            pass
    # Fixed neutral epoch for bit-for-bit build reproducibility
    return "1970-01-01T00:00:00Z"

def build_target(target, output_dir=None, clean=False, timestamp=None):
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    slots_path = os.path.join(repo_root, "registry", "slots", f"{target}.json")

    if not os.path.exists(slots_path):
        raise FileNotFoundError(f"Target slot mapping not found: {slots_path}")

    with open(slots_path, "r", encoding="utf-8") as f:
        target_data = json.load(f)

    if output_dir is None:
        output_dir = os.path.join(repo_root, "generated", target)
    output_dir = os.path.abspath(output_dir)

    if clean and os.path.exists(output_dir):
        # Clean existing files
        for root, dirs, files in os.walk(output_dir, topdown=False):
            for file in files:
                os.remove(os.path.join(root, file))
            for d in dirs:
                os.rmdir(os.path.join(root, d))

    os.makedirs(output_dir, exist_ok=True)

    print(f"Building target '{target}' ({target_data.get('target_name', target)}) -> {output_dir}")
    slots = target_data.get("slots", {})
    manifest_entries = []

    for slot_key, slot_info in sorted(slots.items()):
        asset_id = slot_info["asset_id"]
        slot_rel_path = slot_info.get("slot_path", slot_key)
        aliases = sorted(slot_info.get("aliases", []))

        # Find asset definition by scanning registry/assets/*.json
        asset_file_candidate = None
        for fname in os.listdir(os.path.join(repo_root, "registry", "assets")):
            if fname.endswith(".json"):
                cand = os.path.join(repo_root, "registry", "assets", fname)
                with open(cand, "r", encoding="utf-8") as cf:
                    try:
                        data = json.load(cf)
                        if data.get("id") == asset_id:
                            asset_file_candidate = cand
                            break
                    except Exception:
                        pass

        if not asset_file_candidate:
            raise FileNotFoundError(f"Asset metadata for id '{asset_id}' not found in registry/assets/")

        with open(asset_file_candidate, "r", encoding="utf-8") as af:
            asset_meta = json.load(af)

        source_file_rel = asset_meta["file"]
        source_file_path = os.path.join(repo_root, source_file_rel)
        if not os.path.exists(source_file_path):
            raise FileNotFoundError(f"Source asset file does not exist: {source_file_path}")

        # Check source hash integrity
        actual_sha256 = compute_sha256(source_file_path)
        expected_sha256 = asset_meta.get("sha256")
        if expected_sha256 and actual_sha256 != expected_sha256:
            raise ValueError(f"Hash mismatch for source {source_file_path}: expected {expected_sha256}, got {actual_sha256}")

        with open(source_file_path, "rb") as sf:
            source_bytes = sf.read()

        # Perform target-specific transformation
        category = slot_info.get("category", "").lower()
        if target in ("rm2000", "rm2003") and category == "charset":
            target_png = transform_rgba_to_indexed_png(source_bytes, 288, 256)
        elif target in ("rm2000", "rm2003") and category == "chipset":
            target_png = transform_rgba_to_indexed_png(source_bytes, 480, 256)
        elif target == "rmxp" and category == "character":
            char_idx = slot_info.get("character_index", 0)
            target_png = transform_canonical_to_rmxp_character(source_bytes, char_idx=char_idx)
        else:
            raise NotImplementedError(f"Target transformation for {target}/{category} is not yet implemented")

        target_sha256 = hashlib.sha256(target_png).hexdigest()

        # Write primary slot
        dest_primary = os.path.join(output_dir, slot_rel_path)
        os.makedirs(os.path.dirname(dest_primary), exist_ok=True)
        with open(dest_primary, "wb") as pf:
            pf.write(target_png)

        print(f"  [TRANSFORM] {source_file_rel} -> {slot_rel_path} (SHA-256: {target_sha256[:12]}...)")

        category_name = slot_info.get("category", "")

        manifest_entries.append({
            "slot": slot_rel_path,
            "category": category_name,
            "is_primary": True,
            "asset_id": asset_id,
            "sha256": target_sha256,
            "test_only": slot_info.get("test_only", False)
        })

        # Write aliases
        for alias_rel in aliases:
            dest_alias = os.path.join(output_dir, alias_rel)
            os.makedirs(os.path.dirname(dest_alias), exist_ok=True)
            with open(dest_alias, "wb") as af:
                af.write(target_png)
            print(f"  [ALIAS] {alias_rel} <- {slot_rel_path}")
            manifest_entries.append({
                "slot": alias_rel,
                "category": category_name,
                "is_primary": False,
                "primary_slot": slot_rel_path,
                "asset_id": asset_id,
                "sha256": target_sha256,
                "test_only": slot_info.get("test_only", False)
            })

    # Write build manifest (deterministic)
    manifest = {
        "target": target,
        "target_name": target_data.get("target_name"),
        "engine": target_data.get("engine"),
        "reference_source": target_data.get("reference_source"),
        "timestamp": str(timestamp) if timestamp is not None else get_reproducible_timestamp(),
        "entries": manifest_entries
    }
    manifest_path = os.path.join(output_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as mf:
        json.dump(manifest, mf, indent=2)

    print(f"Target build complete: {len(manifest_entries)} files placed in {output_dir}")
    print(f"Manifest written: {manifest_path}")

def main():
    parser = argparse.ArgumentParser(description="SuperRTP Target Builder")
    parser.add_argument("--target", required=True, help="Target RTP name (e.g. rm2000)")
    parser.add_argument("--output-dir", default=None, help="Custom output directory")
    parser.add_argument("--clean", action="store_true", help="Clean output directory before building")
    args = parser.parse_args()

    build_target(args.target, args.output_dir, args.clean)

if __name__ == "__main__":
    main()
