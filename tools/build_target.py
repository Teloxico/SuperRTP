#!/usr/bin/env python3
"""
Deterministic target builder: canonical registry assets -> one engine target pack.

Pipeline for every slot in registry/slots/<target>.json:
  1. load the canonical asset metadata and verify the source file hash
  2. verify the asset's provenance record (clean-room attestation, license)
  3. transform the source with the (target, category) transform from tools/transforms.py
  4. check the result against the slot's declared dimensions
  5. write the primary slot file and every alias, then a reproducible manifest.json

Output is byte-for-byte reproducible. manifest.json bytes are hash-bound in committed
runtime evidence, so its field order and formatting are part of the contract.

Usage:
  python3 tools/build_target.py --target rm2000 [--output-dir generated/rm2000] [--clean]
"""

import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import transforms
from png_utils import read_png
from registry import asset_source_path, find_asset, list_targets, load_slot_mapping, verify_provenance
from repo import REPO_ROOT, build_timestamp, resolve_within, sha256_bytes, write_json

# Optional slot fields copied into manifest entries, in manifest order.
TRANSFORM_METADATA_FIELDS = (
    "character_index",
    "source_character_indices",
    "direction_mode",
    "animation_patterns",
    "runtime_reference",
    "transform_policy",
)


def _indexed(source: bytes, asset_meta: dict, slot: dict) -> bytes:
    dims = asset_meta["dimensions"]
    return transforms.transform_rgba_to_indexed_png(source, dims["width"], dims["height"])


# (target, lower-case slot category) -> transform(source_bytes, asset_meta, slot_info)
TRANSFORMS = {
    ("rm2000", "charset"): _indexed,
    ("rm2003", "charset"): _indexed,
    ("rm2000", "chipset"): _indexed,
    ("rm2003", "chipset"): _indexed,
    ("rmxp", "character"): lambda src, meta, slot: transforms.transform_canonical_to_rmxp_character(src, char_idx=slot.get("character_index", 0)),
    ("rmvx", "character"): lambda src, meta, slot: transforms.transform_canonical_to_rmvx_character(src, source_indices=slot.get("source_character_indices")),
    ("rmvxace", "character"): lambda src, meta, slot: transforms.transform_canonical_to_rmvxace_character(src, source_indices=slot.get("source_character_indices")),
    ("wolf", "character"): lambda src, meta, slot: transforms.transform_canonical_to_wolf_character(src, char_idx=slot.get("character_index", 0)),
}


def load_canonical_source(asset_id: str):
    """Returns (asset_meta, source_bytes) after checking the source hash and its provenance."""
    _, asset_meta = find_asset(asset_id)
    source_path = asset_source_path(asset_meta)
    if not os.path.exists(source_path):
        raise FileNotFoundError(f"Source asset file does not exist: {source_path}")
    with open(source_path, "rb") as f:
        source = f.read()
    actual = sha256_bytes(source)
    if actual != asset_meta["sha256"]:
        raise ValueError(f"Hash mismatch for source {source_path}: expected {asset_meta['sha256']}, got {actual}")
    verify_provenance(asset_id, actual)
    return asset_meta, source


def transform_slot(target: str, slot_info: dict, asset_meta: dict, source: bytes) -> bytes:
    category = slot_info["category"].lower()
    transform = TRANSFORMS.get((target, category))
    if transform is None:
        raise ValueError(f"No transform is defined for target '{target}' category '{slot_info['category']}'")
    png = transform(source, asset_meta, slot_info)

    declared = slot_info.get("dimensions")
    if declared:
        image = read_png(png)
        if [image.width, image.height] != list(declared):
            raise ValueError(f"Transform for {slot_info['slot_path']} produced {image.width}x{image.height}, slot declares {declared[0]}x{declared[1]}")
    return png


def _manifest_entry(slot_path: str, slot_info: dict, asset_id: str, digest: str, primary_slot: str = None) -> dict:
    entry = {"slot": slot_path, "category": slot_info.get("category", ""), "is_primary": primary_slot is None}
    if primary_slot is not None:
        entry["primary_slot"] = primary_slot
    entry.update({"asset_id": asset_id, "sha256": digest, "test_only": slot_info.get("test_only", False)})
    for field in TRANSFORM_METADATA_FIELDS:
        if field in slot_info:
            entry[field] = slot_info[field]
    return entry


def _clean_output_dir(output_dir: str) -> None:
    """
    Empties a previous build output.

    Refuses anything that does not look like a SuperRTP pack (non-empty without a
    manifest.json) and anything containing the repository, so a mistyped
    --output-dir cannot delete unrelated files.
    """
    if not os.path.exists(output_dir):
        return
    if os.path.commonpath([output_dir, REPO_ROOT]) == output_dir:
        raise ValueError(f"Refusing to clean '{output_dir}': it contains the repository")
    entries = os.listdir(output_dir)
    if entries and "manifest.json" not in entries:
        raise ValueError(f"Refusing to clean '{output_dir}': it is not empty and has no SuperRTP manifest.json")
    for name in entries:
        path = os.path.join(output_dir, name)
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        else:
            os.remove(path)


def build_target(target: str, output_dir: str = None, clean: bool = False, timestamp: str = None) -> dict:
    """Builds `target` into `output_dir` (default generated/<target>); returns the manifest."""
    target_data = load_slot_mapping(target)
    output_dir = os.path.abspath(output_dir or os.path.join(REPO_ROOT, "generated", target))
    if clean:
        _clean_output_dir(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    print(f"Building target '{target}' ({target_data.get('target_name', target)}) -> {output_dir}")
    entries = []
    for _, slot_info in sorted(target_data["slots"].items()):
        asset_id = slot_info["asset_id"]
        slot_path = slot_info["slot_path"]
        asset_meta, source = load_canonical_source(asset_id)
        png = transform_slot(target, slot_info, asset_meta, source)
        digest = sha256_bytes(png)

        for rel_path in [slot_path] + sorted(slot_info.get("aliases", [])):
            dest = resolve_within(output_dir, rel_path)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as f:
                f.write(png)

        print(f"  [TRANSFORM] {asset_meta['file']} -> {slot_path} (SHA-256: {digest[:12]}...)")
        entries.append(_manifest_entry(slot_path, slot_info, asset_id, digest))
        for alias in sorted(slot_info.get("aliases", [])):
            print(f"  [ALIAS] {alias} <- {slot_path}")
            entries.append(_manifest_entry(alias, slot_info, asset_id, digest, primary_slot=slot_path))

    manifest = {
        "target": target,
        "target_name": target_data.get("target_name"),
        "engine": target_data.get("engine"),
        "reference_source": target_data.get("reference_source"),
        "timestamp": str(timestamp) if timestamp is not None else build_timestamp(),
        "entries": entries,
    }
    manifest_path = os.path.join(output_dir, "manifest.json")
    write_json(manifest_path, manifest, trailing_newline=False)
    print(f"Target build complete: {len(entries)} files placed in {output_dir}")
    print(f"Manifest written: {manifest_path}")
    return manifest


def main():
    parser = argparse.ArgumentParser(description="SuperRTP Target Builder")
    parser.add_argument("--target", required=True, choices=list_targets(), help="Target RTP name")
    parser.add_argument("--output-dir", default=None, help="Output directory (default: generated/<target>)")
    parser.add_argument("--clean", action="store_true", help="Empty the output directory before building")
    args = parser.parse_args()
    build_target(args.target, args.output_dir, args.clean)


if __name__ == "__main__":
    main()
