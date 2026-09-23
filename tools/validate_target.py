#!/usr/bin/env python3
"""
Deterministic validator for generated SuperRTP target packs.

Checks, in order:
  1. Registry records (slot mapping, asset metadata, provenance) conform to their schemas,
     and alias lists are a disjoint union of upstream aliases and emitted case variants.
  2. The manifest identifies the right target, and its entries are exactly the files the
     registry declares (every primary slot and alias, nothing else, no stray files).
  3. Each entry agrees with the registry (category, asset id, transform metadata) and its
     file hash matches the manifest.
  4. Each PNG meets its engine format spec (dimensions, color type, chunks, palette and
     alpha rules) and its idle-column arrows point the way its row says.
  5. Each file's pixels equal the deterministic transform of the canonical source, and the
     source's provenance passes the clean-room rules.

Engine rules are documented with sources in docs/engine-facts.md.

Usage:
  python3 tools/validate_target.py --target rm2000 [--target-dir generated/rm2000]
"""

import argparse
import os
import struct
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from build_target import load_canonical_source, transform_slot
from png_utils import COLOR_TYPE_INDEXED, COLOR_TYPE_RGBA, PngFormatError, parse_png_chunks, read_png
from registry import find_asset, find_provenance, list_targets, load_schema, load_slot_mapping, verify_provenance
from repo import REPO_ROOT, load_json, resolve_within, sha256_file
from schema_validator import validate_schema
from transforms import RMXP_LAYOUT

# ---------------------------------------------------------------------------
# PNG format specifications
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PngSpec:
    label: str               # used in messages, e.g. "XP Character"
    width: int
    height: int
    color_type: int
    forbidden_chunks: tuple = ()


CHARSET_SPEC = PngSpec("CharSet", 288, 256, COLOR_TYPE_INDEXED)
CHIPSET_SPEC = PngSpec("ChipSet", 480, 256, COLOR_TYPE_INDEXED)
RMXP_SPEC = PngSpec("XP Character", 96, 128, COLOR_TYPE_RGBA, ("PLTE",))
VX_SPEC = PngSpec("VX Character", 288, 256, COLOR_TYPE_RGBA, ("PLTE",))
VXACE_SPEC = PngSpec("VX Ace Character", 288, 256, COLOR_TYPE_RGBA, ("PLTE",))
WOLF_SPEC = PngSpec("WOLF Character", 72, 128, COLOR_TYPE_RGBA, ("PLTE", "tRNS"))

_COLOR_TYPE_NAMES = {COLOR_TYPE_INDEXED: "3 (indexed-color)", COLOR_TYPE_RGBA: "6 (RGBA truecolor)"}


def _read_checked(filepath: str, spec: PngSpec):
    """Reads a PNG and enforces chunk structure, dimensions and color model for `spec`."""
    with open(filepath, "rb") as f:
        data = f.read()
    chunks = parse_png_chunks(data)
    chunk_types = [ctype for ctype, _ in chunks]
    if not chunk_types or chunk_types[0] != "IHDR" or len(chunks[0][1]) != 13:
        raise ValueError("PNG must start with IHDR chunk")
    if chunk_types[-1] != "IEND":
        raise ValueError("PNG must terminate with IEND chunk")
    if "IDAT" not in chunk_types:
        raise ValueError("Missing IDAT chunk")
    for ctype in spec.forbidden_chunks:
        if ctype in chunk_types:
            raise ValueError(f"Unexpected {ctype} chunk: {spec.label} sheets must be truecolor RGBA with the alpha channel stored directly")
    if spec.color_type == COLOR_TYPE_INDEXED and "PLTE" not in chunk_types:
        raise ValueError(f"Missing required PLTE (Palette) chunk for indexed {spec.label}")

    # Header checks come before decoding so a wrong size reports as a size error.
    width, height, _, color_type = struct.unpack(">IIBB", chunks[0][1][:10])
    if (width, height) != (spec.width, spec.height):
        raise ValueError(f"Invalid {spec.label} dimensions: expected {spec.width}x{spec.height}, got {width}x{height}")
    if color_type != spec.color_type:
        raise ValueError(f"Invalid color type: expected {_COLOR_TYPE_NAMES[spec.color_type]}, got {color_type}")
    return read_png(data)


def _check_indexed_palette(image) -> dict:
    """RM2000/2003: <= 256 colors; palette index 0 is the transparent color."""
    if len(image.palette) > 256:
        raise ValueError(f"Palette exceeds 256 colors: {len(image.palette)}")
    has_trns = "tRNS" in image.chunk_types
    if has_trns and image.trns and image.trns[0] != 0:
        raise ValueError(f"Transparency index 0 in tRNS has non-zero alpha ({image.trns[0]})")
    return {"num_colors": len(image.palette), "transparent_index": 0, "has_trns": has_trns}


def _check_alpha_range(rgba: bytes, spec: PngSpec) -> None:
    alphas = set(rgba[3::4])
    if 0 not in alphas:
        raise ValueError(f"Missing transparent pixels (alpha 0) in {spec.label} sheet")
    if 255 not in alphas:
        raise ValueError(f"Missing fully opaque pixels (alpha 255) in {spec.label} sheet")


# Calibration arrow probes inside one 24x32 idle cell: direction -> (tip, notch, tip side, notch side).
# The calibration sprite draws an opaque arrow tip and leaves a transparent notch opposite it.
_ARROW_PROBES = {
    "DOWN": ((11, 21), (11, 6), "center-bottom", "center-top"),
    "LEFT": ((4, 13), (19, 13), "center-left", "center-right"),
    "RIGHT": ((19, 13), (4, 13), "center-right", "center-left"),
    "UP": ((11, 5), (11, 21), "center-top", "center-bottom"),
}
_TARGET_ROWS = ("DOWN", "LEFT", "RIGHT", "UP")  # XP, VX, VX Ace and WOLF row order


def _check_idle_arrows(rgba: bytes, width: int, origin_x: int, origin_y: int, prefix: str = "", idle_column: int = 1) -> None:
    """Checks that each row's idle cell (`idle_column`) at the given origin shows its direction's arrow."""
    idle_x = origin_x + idle_column * 24
    for row, direction in enumerate(_TARGET_ROWS):
        (tx, ty), (nx, ny), tip_side, notch_side = _ARROW_PROBES[direction]
        cell_y = origin_y + row * 32
        tip_alpha = rgba[((cell_y + ty) * width + idle_x + tx) * 4 + 3]
        notch_alpha = rgba[((cell_y + ny) * width + idle_x + nx) * 4 + 3]
        if tip_alpha == 0:
            raise ValueError(f"{prefix}Row {row} arrow orientation error: expected {direction} facing arrow tip at {tip_side}")
        if notch_alpha != 0:
            raise ValueError(f"{prefix}Row {row} arrow orientation error: expected {direction} facing arrow notch at {notch_side}")


def validate_png_charset(filepath):
    """RPG Maker 2000/2003 CharSet: 288x256 indexed, 4x2 characters of 3x4 24x32 cells."""
    image = _read_checked(filepath, CHARSET_SPEC)
    palette_info = _check_indexed_palette(image)
    return {"width": image.width, "height": image.height, "bit_depth": image.bit_depth, "color_type": image.color_type,
            **palette_info, "characters_grid": "4x2", "frame_cell": "24x32"}


def validate_png_chipset(filepath):
    """RPG Maker 2000/2003 ChipSet: 480x256 indexed, 30x16 tiles of 16x16."""
    image = _read_checked(filepath, CHIPSET_SPEC)
    palette_info = _check_indexed_palette(image)
    return {"width": image.width, "height": image.height, "bit_depth": image.bit_depth, "color_type": image.color_type,
            **palette_info, "tile_grid": "30x16", "tile_size": "16x16"}


def validate_png_rmxp_character(filepath):
    """RPG Maker XP character: 96x128 RGBA, 4x4 cells laid out as transforms.RMXP_LAYOUT (IDLE in two columns)."""
    image = _read_checked(filepath, RMXP_SPEC)
    rgba = image.pixels
    _check_alpha_range(rgba, RMXP_SPEC)
    idle = [i for i, phase in enumerate(RMXP_LAYOUT.columns) if phase == "IDLE"]
    for y in range(image.height):
        row = y * image.width * 4
        first = rgba[row + idle[0] * 96:row + (idle[0] + 1) * 96]
        for column in idle[1:]:
            if rgba[row + column * 96:row + (column + 1) * 96] != first:
                raise ValueError(f"Idle column {column} does not match idle column {idle[0]} at row {y // 32}, local y {y % 32}")
    _check_idle_arrows(rgba, image.width, 0, 0, idle_column=idle[0])
    return {"width": image.width, "height": image.height, "bit_depth": image.bit_depth, "color_type": image.color_type,
            "num_colors": "truecolor-rgba", "has_trns": False, "frame_cell": "24x32", "grid": "4x4",
            "directions": list(_TARGET_ROWS)}


def validate_png_vx_family_character(filepath, engine_name="VX"):
    """RPG Maker VX / VX Ace standard sheet: 288x256 RGBA, 4x2 characters of 3x4 24x32 cells."""
    spec = VXACE_SPEC if engine_name == "VX Ace" else VX_SPEC
    image = _read_checked(filepath, spec)
    rgba = image.pixels
    _check_alpha_range(rgba, spec)
    for char_idx in range(8):
        _check_idle_arrows(rgba, image.width, (char_idx % 4) * 72, (char_idx // 4) * 128, prefix=f"Character {char_idx} ")
    return {"width": image.width, "height": image.height, "bit_depth": image.bit_depth, "color_type": image.color_type,
            "num_colors": "truecolor-rgba", "has_trns": False, "frame_cell": "24x32", "character_block": "72x128",
            "grid": "4x2 characters (12x8 cells)", "directions": list(_TARGET_ROWS)}


def validate_png_rmvx_character(filepath):
    return validate_png_vx_family_character(filepath, engine_name="VX")


def validate_png_rmvxace_character(filepath):
    return validate_png_vx_family_character(filepath, engine_name="VX Ace")


# WOLF filename suffixes that switch CharaChip into a different layout (docs/engine-facts.md).
WOLF_SPECIAL_SUFFIXES = ("T.png", "TX.png", "$.png")


def validate_png_wolf_character(filepath):
    """WOLF RPG Editor 3 CharaChip: 72x128 RGBA, 3 patterns x 4 directions, standard filename."""
    basename = os.path.basename(filepath)
    if basename.endswith(WOLF_SPECIAL_SUFFIXES):
        raise ValueError(f"WOLF character filename '{basename}' invokes special filename mode (T, TX, or $); out of scope for standard CharaChip")
    image = _read_checked(filepath, WOLF_SPEC)
    rgba = image.pixels
    _check_alpha_range(rgba, WOLF_SPEC)
    _check_idle_arrows(rgba, image.width, 0, 0)
    return {"width": image.width, "height": image.height, "bit_depth": image.bit_depth, "color_type": image.color_type,
            "num_colors": "truecolor-rgba", "has_trns": False, "frame_cell": "24x32", "character_block": "72x128",
            "grid": "1 character (3x4 cells)", "directions": list(_TARGET_ROWS),
            "animation_patterns": ["STEP_LEFT", "IDLE", "STEP_RIGHT"], "cells_verified": 12}


# (target, lower-case category) -> PNG validator
PNG_VALIDATORS = {
    ("rm2000", "charset"): validate_png_charset,
    ("rm2003", "charset"): validate_png_charset,
    ("rm2000", "chipset"): validate_png_chipset,
    ("rm2003", "chipset"): validate_png_chipset,
    ("rmxp", "character"): validate_png_rmxp_character,
    ("rmvx", "character"): validate_png_rmvx_character,
    ("rmvxace", "character"): validate_png_rmvxace_character,
    ("wolf", "character"): validate_png_wolf_character,
}

# ---------------------------------------------------------------------------
# Registry and pack validation
# ---------------------------------------------------------------------------

TRANSFORM_METADATA_FIELDS = ("character_index", "source_character_indices", "direction_mode",
                             "animation_patterns", "runtime_reference", "transform_policy")


def validate_schemas(repo_root, target):
    """Schema-validates the slot mapping plus the asset and provenance record of every slot."""
    slots_data = load_slot_mapping(target)
    validate_schema(slots_data, load_schema("slot_mapping"), path=f"{target}.json")
    asset_schema = load_schema("asset")
    prov_schema = load_schema("provenance")

    for slot_key, slot_info in slots_data["slots"].items():
        aliases = slot_info.get("aliases", [])
        upstream = slot_info.get("upstream_aliases")
        case_vars = slot_info.get("emitted_case_variants")
        if upstream is not None or case_vars is not None:
            up_set, cv_set = set(upstream or []), set(case_vars or [])
            if not up_set.isdisjoint(cv_set):
                raise ValueError(f"Slot '{slot_key}' has overlapping upstream and case variant aliases: {up_set & cv_set}")
            if up_set | cv_set != set(aliases):
                raise ValueError(f"Slot '{slot_key}' aliases union mismatch: (upstream | case_variants) != aliases")
        if slot_info["slot_path"] != slot_key:
            raise ValueError(f"Slot key '{slot_key}' does not match its slot_path '{slot_info['slot_path']}'")
        if slot_info["slot_path"] in aliases:
            raise ValueError(f"Slot '{slot_key}' aliases must not include primary slot_path '{slot_info['slot_path']}'")

        asset_path, asset = find_asset(slot_info["asset_id"])
        validate_schema(asset, asset_schema, path=os.path.basename(asset_path))
        prov_path, prov = find_provenance(slot_info["asset_id"])
        validate_schema(prov, prov_schema, path=os.path.basename(prov_path))
    return True


def expected_pack_files(slots_data: dict) -> dict:
    """Maps every file a pack must contain to (slot_info, primary_slot or None)."""
    expected = {}
    for slot_info in slots_data["slots"].values():
        primary = slot_info["slot_path"]
        expected[primary] = (slot_info, None)
        for alias in slot_info.get("aliases", []):
            if alias in expected:
                raise ValueError(f"Pack path '{alias}' is declared by more than one slot")
            expected[alias] = (slot_info, primary)
    return expected


def _files_on_disk(target_dir: str) -> set:
    found = set()
    for root, _, files in os.walk(target_dir):
        for name in files:
            rel = os.path.relpath(os.path.join(root, name), target_dir).replace(os.sep, "/")
            if rel != "manifest.json":
                found.add(rel)
    return found


def _expected_rgba(target: str, slot_info: dict, cache: dict) -> bytes:
    """RGBA of the deterministic transform for a slot, computed once per slot (aliases share it)."""
    key = slot_info["slot_path"]
    if key not in cache:
        asset_meta, source = load_canonical_source(slot_info["asset_id"])
        cache[key] = read_png(transform_slot(target, slot_info, asset_meta, source)).rgba_bytes()
    return cache[key]


def _validate_entry(target, target_dir, entry, expected, primary_hashes, expected_cache):
    """Validates one manifest entry; returns a list of failure messages (empty on success)."""
    slot = entry.get("slot")
    if slot not in expected:
        return [f"Slot '{slot}' is not declared in the slot mapping registry"]
    slot_info, primary = expected[slot]

    category = entry.get("category")
    if not category:
        return [f"Missing semantic category in manifest entry for {slot}"]
    if category != slot_info["category"]:
        return [f"Category mismatch for slot '{slot}': manifest has '{category}', registry has '{slot_info['category']}'"]
    if entry.get("asset_id") != slot_info["asset_id"]:
        return [f"Asset id mismatch for slot '{slot}': manifest has '{entry.get('asset_id')}', registry has '{slot_info['asset_id']}'"]
    if entry.get("is_primary") != (primary is None) or entry.get("primary_slot") != primary:
        return [f"Primary/alias designation mismatch for slot '{slot}'"]
    for field in TRANSFORM_METADATA_FIELDS:
        if slot_info.get(field) != entry.get(field):
            return [f"Transformation metadata mismatch for slot '{slot}' field '{field}': manifest has {entry.get(field)!r}, registry has {slot_info.get(field)!r}"]

    filepath = resolve_within(target_dir, slot)
    if not os.path.exists(filepath):
        return [f"File missing at {filepath}"]
    actual = sha256_file(filepath)
    if actual != entry.get("sha256"):
        return [f"Hash mismatch in manifest! Expected {entry.get('sha256')}, got {actual}"]
    if primary is not None and primary_hashes.get(primary) not in (None, actual):
        return [f"Alias '{slot}' differs from its primary slot '{primary}'"]

    try:
        specs = PNG_VALIDATORS[(target, category.lower())](filepath)
        print(f"  PASSED PNG specs: {specs['width']}x{specs['height']}, color type {specs['color_type']}")

        if _expected_rgba(target, slot_info, expected_cache) != read_png(filepath).rgba_bytes():
            raise ValueError("Pixels differ from the deterministic transform of the canonical source")
        _, asset_meta = find_asset(slot_info["asset_id"])
        prov = verify_provenance(slot_info["asset_id"], asset_meta["sha256"])
        print(f"  PASSED Canonical source & provenance: License={prov['license']}, SourceType={prov['source_type']}")
    except (ValueError, PngFormatError, OSError) as exc:
        return [f"{type(exc).__name__}: {exc}"]
    return []


def validate_target(target, target_dir=None):
    """Validates one generated pack; prints a report and returns 0 on success, 1 on failure."""
    target_dir = os.path.abspath(target_dir or os.path.join(REPO_ROOT, "generated", target))
    print(f"=== Validating SuperRTP Target '{target}' ===")

    try:
        validate_schemas(REPO_ROOT, target)
        print("  PASSED: All registry metadata conforms to JSON schemas.")
        slots_data = load_slot_mapping(target)
        expected = expected_pack_files(slots_data)
    except (ValueError, OSError) as exc:
        print(f"  FAILED Registry validation: {exc}")
        return 1

    manifest_path = os.path.join(target_dir, "manifest.json")
    if not os.path.exists(manifest_path):
        print(f"  FAILED: Missing build manifest in target directory: {manifest_path}")
        return 1
    manifest = load_json(manifest_path)
    entries = manifest.get("entries", [])
    print(f"Directory: {target_dir}")
    print(f"Target Name: {manifest.get('target_name')}")
    print(f"Engine: {manifest.get('engine')}")
    print(f"Entries to validate: {len(entries)} (registry declares {len(expected)})")

    failures = []
    for field in ("target", "engine", "target_name"):
        want = target if field == "target" else slots_data.get(field)
        if manifest.get(field) != want:
            failures.append(f"Manifest {field} mismatch: expected '{want}', got '{manifest.get(field)}'")

    manifest_slots = [e.get("slot") for e in entries]
    duplicates = sorted({s for s in manifest_slots if manifest_slots.count(s) > 1})
    if duplicates:
        failures.append(f"Manifest lists slots more than once: {duplicates}")
    missing = sorted(set(expected) - set(manifest_slots))
    if missing:
        failures.append(f"Manifest is missing registry-declared files: {missing}")
    stray = sorted(_files_on_disk(target_dir) - set(expected))
    if stray:
        failures.append(f"Target directory contains files not declared by the registry: {stray}")

    primary_hashes = {e.get("slot"): e.get("sha256") for e in entries if e.get("is_primary")}
    validated = 0
    expected_cache = {}
    for entry in entries:
        print(f"\nChecking [{entry.get('slot')}]...")
        entry_failures = _validate_entry(target, target_dir, entry, expected, primary_hashes, expected_cache)
        for msg in entry_failures:
            print(f"  FAILED: {msg}")
        failures.extend(entry_failures)
        if not entry_failures:
            validated += 1

    print("\n" + "=" * 45)
    if failures or validated == 0:
        for msg in failures:
            print(f"  FAILED: {msg}")
        print(f"VALIDATION FAILED: {validated} passed out of {len(entries)}.")
        return 1
    print(f"ALL CHECKS PASSED: {validated} target files verified successfully.")
    return 0


def main():
    parser = argparse.ArgumentParser(description="SuperRTP Target Validator")
    parser.add_argument("--target", required=True, choices=list_targets(), help="Target name")
    parser.add_argument("--target-dir", default=None, help="Custom target directory")
    args = parser.parse_args()
    sys.exit(validate_target(args.target, args.target_dir))


if __name__ == "__main__":
    main()
