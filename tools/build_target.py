#!/usr/bin/env python3
"""
Deterministic Target Builder for SuperRTP.

Builds engine-specific runtime packages from canonical assets and slot mappings:
  canonical source -> provenance -> semantic identity -> slot mapping -> target output

Usage:
  python3 tools/build_target.py --target rm2000 [--output-dir generated/rm2000] [--clean]
"""

import os
import sys
import json
import shutil
import hashlib
import argparse
from datetime import datetime, timezone

def compute_sha256(filepath):
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def build_target(target, output_dir=None, clean=False):
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
        print(f"Cleaning existing target output directory: {output_dir}")
        shutil.rmtree(output_dir)

    os.makedirs(output_dir, exist_ok=True)

    print(f"Building target '{target}' ({target_data.get('target_name', target)}) -> {output_dir}")
    slots = target_data.get("slots", {})
    manifest_entries = []

    for slot_key, slot_info in slots.items():
        asset_id = slot_info["asset_id"]
        slot_rel_path = slot_info.get("slot_path", slot_key)
        aliases = slot_info.get("aliases", [])

        # Find asset definition
        # Convert asset_id 'test.calibration.walking-character' to filename
        asset_file_candidate = os.path.join(repo_root, "registry", "assets", f"{asset_id.replace('.', '_')}.json")
        if not os.path.exists(asset_file_candidate):
            # Fallback search in registry/assets
            found = False
            for fname in os.listdir(os.path.join(repo_root, "registry", "assets")):
                if fname.endswith(".json"):
                    cand_path = os.path.join(repo_root, "registry", "assets", fname)
                    with open(cand_path, "r", encoding="utf-8") as cf:
                        data = json.load(cf)
                        if data.get("id") == asset_id:
                            asset_file_candidate = cand_path
                            found = True
                            break
            if not found:
                raise FileNotFoundError(f"Asset definition for '{asset_id}' not found in registry/assets/")

        with open(asset_file_candidate, "r", encoding="utf-8") as af:
            asset_meta = json.load(af)

        source_png_rel = asset_meta["file"]
        source_png_path = os.path.join(repo_root, source_png_rel)
        if not os.path.exists(source_png_path):
            raise FileNotFoundError(f"Source asset file does not exist: {source_png_path}")

        # Check integrity
        actual_sha256 = compute_sha256(source_png_path)
        expected_sha256 = asset_meta.get("sha256")
        if expected_sha256 and actual_sha256 != expected_sha256:
            raise ValueError(f"Hash mismatch for {source_png_path}: expected {expected_sha256}, got {actual_sha256}")

        # Write primary slot
        dest_primary = os.path.join(output_dir, slot_rel_path)
        os.makedirs(os.path.dirname(dest_primary), exist_ok=True)
        shutil.copy2(source_png_path, dest_primary)
        print(f"  [SLOT] {slot_rel_path} <- {source_png_rel} (SHA-256: {actual_sha256[:12]}...)")

        manifest_entries.append({
            "slot": slot_rel_path,
            "is_primary": True,
            "asset_id": asset_id,
            "sha256": actual_sha256,
            "test_only": slot_info.get("test_only", False)
        })

        # Write aliases
        for alias_rel in aliases:
            dest_alias = os.path.join(output_dir, alias_rel)
            os.makedirs(os.path.dirname(dest_alias), exist_ok=True)
            shutil.copy2(source_png_path, dest_alias)
            print(f"  [ALIAS] {alias_rel} <- {slot_rel_path}")
            manifest_entries.append({
                "slot": alias_rel,
                "is_primary": False,
                "primary_slot": slot_rel_path,
                "asset_id": asset_id,
                "sha256": actual_sha256,
                "test_only": slot_info.get("test_only", False)
            })

    # Write build manifest
    manifest = {
        "target": target,
        "target_name": target_data.get("target_name"),
        "engine": target_data.get("engine"),
        "built_at": datetime.now(timezone.utc).isoformat(),
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
