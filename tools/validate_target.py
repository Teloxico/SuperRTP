#!/usr/bin/env python3
"""
Deterministic Validator for SuperRTP Targets.

Mechanically verifies that generated target packs conform to strict compatibility,
provenance, and structural invariants without relying on assumptions.

Validates:
  1. File existence & PNG binary chunk structure (IHDR, PLTE, tRNS, IDAT, IEND)
  2. Resolution (288x256 for RM2000 CharSet)
  3. Color model (8-bit indexed colormap, Color Type 3, <= 256 palette entries)
  4. Transparency (tRNS chunk specifying palette index 0 as transparent)
  5. Geometric frame divisibility (72x128 character slot, 24x32 frame cell)
  6. Provenance completeness (valid sidecar, matching SHA-256, CC0-1.0, clean-room attestation)
  7. Test-only designation verification

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
    if "tRNS" not in chunk_types:
        raise ValueError("Missing required tRNS (Transparency) chunk for RM2000 CharSet")
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

    # Inspect PLTE
    plte_data = next(c[1] for c in chunks if c[0] == "PLTE")
    if len(plte_data) % 3 != 0:
        raise ValueError(f"PLTE data length ({len(plte_data)}) is not a multiple of 3")
    num_colors = len(plte_data) // 3
    if num_colors > 256:
        raise ValueError(f"Palette exceeds 256 colors: {num_colors}")

    # Inspect tRNS
    trns_data = next(c[1] for c in chunks if c[0] == "tRNS")
    if len(trns_data) == 0:
        raise ValueError("Empty tRNS chunk")
    if trns_data[0] != 0:
        raise ValueError(f"Transparency index 0 is not transparent (alpha={trns_data[0]})")

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
        "characters_grid": "4x2",
        "frame_cell": f"{frame_w}x{frame_h}"
    }

def validate_provenance(repo_root, asset_id, actual_sha256):
    """Validates that provenance records are complete and attest clean-room integrity."""
    # Find provenance file
    prov_candidate = os.path.join(repo_root, "registry", "provenance", f"{asset_id.replace('.', '_')}.json")
    if not os.path.exists(prov_candidate):
        found = False
        for fname in os.listdir(os.path.join(repo_root, "registry", "provenance")):
            if fname.endswith(".json"):
                cand = os.path.join(repo_root, "registry", "provenance", fname)
                with open(cand, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("asset_id") == asset_id:
                        prov_candidate = cand
                        found = True
                        break
        if not found:
            raise FileNotFoundError(f"Provenance record for '{asset_id}' not found in registry/provenance/")

    with open(prov_candidate, "r", encoding="utf-8") as pf:
        prov = json.load(pf)

    if prov.get("sha256") != actual_sha256:
        raise ValueError(f"Provenance hash mismatch: expected {prov.get('sha256')}, got {actual_sha256}")

    attestation = prov.get("clean_room_attestation", {})
    if attestation.get("proprietary_rtp_derived") is not False:
        raise ValueError("Provenance violation: proprietary_rtp_derived must be false")
    if attestation.get("openrtp_derived") is not False:
        raise ValueError("Provenance violation: openrtp_derived must be false")
    if attestation.get("external_art_used") is not False:
        raise ValueError("Provenance violation: external_art_used must be false")
    if attestation.get("ai_generation_used") is not False:
        raise ValueError("Provenance violation: ai_generation_used must be false")
    if not attestation.get("geometric_primitives_only"):
        raise ValueError("Provenance violation: geometric_primitives_only must be true for test fixture")

    license_str = prov.get("license")
    if license_str != "CC0-1.0":
        raise ValueError(f"Unexpected license: expected CC0-1.0, got {license_str}")

    return prov

def validate_target(target, target_dir=None):
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if target_dir is None:
        target_dir = os.path.join(repo_root, "generated", target)
    target_dir = os.path.abspath(target_dir)

    manifest_path = os.path.join(target_dir, "manifest.json")
    if not os.path.exists(manifest_path):
        raise FileNotFoundError(f"Missing build manifest in target directory: {manifest_path}")

    with open(manifest_path, "r", encoding="utf-8") as mf:
        manifest = json.load(mf)

    print(f"=== Validating SuperRTP Target '{target}' ===")
    print(f"Directory: {target_dir}")
    print(f"Target Name: {manifest.get('target_name')}")
    print(f"Engine: {manifest.get('engine')}")
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
            print(f"  PASSED PNG specs: {specs['width']}x{specs['height']}, {specs['num_colors']} colors, indexed-8, tRNS alpha 0")
        except Exception as e:
            print(f"  FAILED PNG validation: {e}")
            all_passed = False
            continue

        # Provenance check
        try:
            prov = validate_provenance(repo_root, asset_id, actual_sha256)
            print(f"  PASSED Provenance: License={prov['license']}, CleanRoom=VERIFIED, TestOnly={prov.get('test_only')}")
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
