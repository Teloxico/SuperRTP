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

    for entry in manifest.get("entries", []):
        slot = entry["slot"]
        asset_id = entry["asset_id"]
        filepath = os.path.join(target_dir, slot)
        print(f"\nChecking [{slot}]...")

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

        # PNG Specification check
        try:
            specs = validate_png_charset(filepath)
            print(f"  PASSED PNG specs: {specs['width']}x{specs['height']}, {specs['num_colors']} colors, indexed-8, index 0 transparent (tRNS={specs['has_trns']})")
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
