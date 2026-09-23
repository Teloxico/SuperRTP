#!/usr/bin/env python3
"""Generate clean-room alternatives for all 5,672 inventoried compatibility paths."""

import argparse
import csv
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys

TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)

from asset_generation.procedural_audio import audio_policy, render_audio
from asset_generation.procedural_common import semantic_stem
from asset_generation.procedural_visuals import encode_visual, render_visual, visual_policy
from png_utils import read_png
from repo import REPO_ROOT, resolve_within, sha256_file, write_json


SPEC_PATH = os.path.join(REPO_ROOT, "specs", "generation", "full-inventory.v2.json")
INVENTORY_DIR = os.path.join(REPO_ROOT, "registry", "upstream-assets")
BASE_ENGINES = ("rm2000", "rm2003", "rmxp", "rmvx", "rmvxace", "wolf")
VISUAL_EXTENSIONS = {".png", ".jpg", ".ico"}
AUDIO_EXTENSIONS = {".mid", ".wav", ".ogg"}


FLUX_SOURCE = "flux2-klein-4b"


def load_spec(path=SPEC_PATH):
    with open(path, encoding="utf-8") as handle:
        spec = json.load(handle)
    spec["_path"] = path
    bound = [(spec["scope"]["inventory_index"], spec["scope"]["inventory_index_sha256"])]
    for key in ("visual_direction", "art_direction"):   # v1 used a direction board, v2 the FLUX art direction
        if key in spec:
            bound.append((spec[key]["path"], spec[key]["sha256"]))
    for relative, expected in bound:
        actual = sha256_file(os.path.join(REPO_ROOT, relative))
        if actual != expected:
            raise ValueError(f"Generation input hash mismatch for {relative}: expected {expected}, got {actual}")
    if spec["clean_room_attestation"]["proprietary_creative_inputs_used"] is not False:
        raise ValueError("Full-inventory generation spec violates the clean-room boundary")
    return spec


def _category(engine: str, path: str) -> str:
    parts = path.split("/")
    if len(parts) == 1:
        return "(root)"
    if engine in ("rm2000", "rm2003"):
        return parts[0]
    return "/".join(parts[:2])


def _pack(engine: str, locale: str | None = None) -> str:
    if locale:
        return f"{engine}-{locale}"
    return f"{engine}-en" if engine in ("rm2000", "rm2003") else engine


def _slug(value: str) -> str:
    return "-".join(part for part in value.lower().replace("_", "-").replace("/", "-").split("-") if part)


def _entry(engine: str, pack: str, locale: str, path: str, semantic_id: str | None = None,
           alias_of: str | None = None):
    extension = os.path.splitext(path)[1].lower()
    if extension in VISUAL_EXTENSIONS:
        policy = visual_policy(engine, path)
        family = policy.family
        details = {"width": policy.width, "height": policy.height, "indexed": policy.indexed}
        media = "visual"
    elif extension in AUDIO_EXTENSIONS:
        policy = audio_policy(path)
        family = policy.family
        details = {"duration_seconds": policy.duration_seconds}
        media = "audio"
    else:
        raise ValueError(f"Unexpected creative extension in inventory: {path}")
    creative_id = f"{media}.{_slug(family)}.{semantic_stem(path)}"
    if semantic_id and not semantic_stem(path):
        creative_id += f".{semantic_id}"
    return {
        "engine": engine,
        "pack": pack,
        "locale": locale,
        "path": path,
        "category": _category(engine, path),
        "extension": extension,
        "media": media,
        "family": family,
        "creative_id": creative_id,
        "semantic_id": semantic_id,
        "alias_of": alias_of,
        "details": details,
    }


def build_plan(spec):
    entries = []
    for engine in BASE_ENGINES:
        inventory = os.path.join(INVENTORY_DIR, f"{engine}.txt")
        with open(inventory, encoding="utf-8") as handle:
            for line in handle:
                path = line.rstrip("\n")
                entries.append(_entry(engine, _pack(engine), "en" if engine in ("rm2000", "rm2003") else "base", path))

    aliases = (
        ("rm2000", "rm2000-official-aliases.tsv", (("ja", "japanese_path"),)),
        ("rm2003", "rm2003-official-aliases.tsv", (("ja", "japanese_path"), ("zh-tw", "traditional_chinese_path"))),
    )
    for engine, filename, locales in aliases:
        with open(os.path.join(INVENTORY_DIR, filename), encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                english = row["english_path"]
                for locale, column in locales:
                    path = row[column]
                    if not path:
                        continue
                    alias_of = f"packs/{_pack(engine)}/{english}" if english else None
                    entries.append(_entry(engine, _pack(engine, locale), locale, path, row["semantic_id"], alias_of))

    expected = spec["scope"]["total_output_paths"]
    if len(entries) != expected:
        raise ValueError(f"Plan path count mismatch: expected {expected}, got {len(entries)}")
    seen = set()
    for entry in entries:
        key = (entry["pack"], entry["path"])
        if key in seen:
            raise ValueError(f"Duplicate generated path in plan: {entry['pack']}:{entry['path']}")
        seen.add(key)
    return entries


def _render_key(entry):
    details = entry["details"]
    return (
        entry["creative_id"], entry["extension"], entry["family"],
        details.get("width"), details.get("height"), details.get("indexed"), details.get("duration_seconds"),
    )


def _structured_flux(spec, entry):
    """The structured FLUX RGBA for a visual entry and its sidecar, or (None, None)."""
    generation = spec.get("visual_generation")
    if not generation or generation.get("backend") != FLUX_SOURCE:
        return None, None
    d = entry["details"]
    base = os.path.join(REPO_ROOT, generation["structured_root"], entry["creative_id"],
                        f"{entry['family']}-{d['width']}x{d['height']}")
    if not (os.path.isfile(base + ".rgba") and os.path.isfile(base + ".json")):
        return None, None
    with open(base + ".json", encoding="utf-8") as handle:
        sidecar = json.load(handle)
    with open(base + ".rgba", "rb") as handle:
        rgba = handle.read()
    if hashlib.sha256(rgba).hexdigest() != sidecar.get("rgba_sha256") or len(rgba) != d["width"] * d["height"] * 4:
        raise ValueError(f"Structured FLUX asset does not match its sidecar: {base}.rgba")
    return rgba, sidecar


def _render(entry, spec=None):
    """Returns (encoded bytes, visual source, structured sidecar SHA-256 or None)."""
    if entry["media"] == "visual":
        policy = visual_policy(entry["engine"], entry["path"])
        rgba, sidecar = _structured_flux(spec or {}, entry)
        if rgba is not None:
            return encode_visual(entry["engine"], entry["path"], policy, rgba, prequantized=True), FLUX_SOURCE, \
                hashlib.sha256(json.dumps(sidecar, sort_keys=True).encode()).hexdigest()
        return encode_visual(entry["engine"], entry["path"], policy, render_visual(entry["engine"], entry["path"], policy)), \
            "procedural", None
    return render_audio(entry["path"], entry["creative_id"], audio_policy(entry["path"])), "procedural", None


def _write_bytes(path: str, data: bytes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".superrtp-tmp"
    with open(temporary, "wb") as handle:
        handle.write(data)
    os.replace(temporary, path)


def _ffmpeg_version():
    result = subprocess.run(["ffmpeg", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError("ffmpeg is required for deterministic JPEG and OGG encoding")
    return result.stdout.splitlines()[0]


def generate(spec, entries):
    root_relative = spec["output_root"]
    root = resolve_within(REPO_ROOT, root_relative)
    manifest_entries = []
    rendered = {}
    sources = {}
    for index, entry in enumerate(entries, 1):
        relative = f"packs/{entry['pack']}/{entry['path']}"
        destination = resolve_within(root, relative)
        source_relative = entry["alias_of"]
        reused_from = None
        if source_relative:
            source = resolve_within(root, source_relative)
            if not os.path.isfile(source):
                raise FileNotFoundError(f"Alias source is missing: {source_relative}")
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            shutil.copyfile(source, destination)
            reused_from = source_relative
            source_info = sources[source_relative]
        else:
            render_key = _render_key(entry)
            if render_key in rendered:
                source_relative = rendered[render_key]
                source = resolve_within(root, source_relative)
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                shutil.copyfile(source, destination)
                reused_from = source_relative
                source_info = sources[source_relative]
            else:
                data, visual_source, structured_sha = _render(entry, spec)
                _write_bytes(destination, data)
                rendered[render_key] = relative
                source_info = (visual_source, structured_sha)
        sources[relative] = source_info
        record = dict(entry)
        record["output"] = relative
        record["sha256"] = sha256_file(destination)
        record["bytes"] = os.path.getsize(destination)
        record["reused_from"] = reused_from
        record["visual_source"] = source_info[0] if entry["media"] == "visual" else None
        record["flux_structured_sidecar_sha256"] = source_info[1]
        manifest_entries.append(record)
        if index == 1 or index % 100 == 0 or index == len(entries):
            print(f"[{index}/{len(entries)}] {entry['pack']}:{entry['path']}", flush=True)

    counts = {}
    for entry in manifest_entries:
        counts[entry["pack"]] = counts.get(entry["pack"], 0) + 1
    manifest = {
        "schema_version": 1,
        "generation_spec": os.path.relpath(spec["_path"], REPO_ROOT),
        "generation_spec_sha256": sha256_file(spec["_path"]),
        "license": spec["license"],
        "status": "candidate-not-active",
        "clean_room_attestation": spec["clean_room_attestation"],
        "visual_direction_sha256": spec.get("visual_direction", {}).get("sha256"),
        "art_direction_sha256": spec.get("art_direction", {}).get("sha256"),
        "visual_source_counts": _source_counts(manifest_entries),
        "ffmpeg_version": _ffmpeg_version(),
        "path_count": len(manifest_entries),
        "pack_counts": dict(sorted(counts.items())),
        "unique_creative_ids": len({entry["creative_id"] for entry in manifest_entries}),
        "unique_content_hashes": len({entry["sha256"] for entry in manifest_entries}),
        "entries": manifest_entries,
    }
    write_json(os.path.join(root, "manifest.json"), manifest)
    provenance = {
        "collection_id": spec["id"],
        "version": spec["version"],
        "license": spec["license"],
        "generation_date": spec["generation_date"],
        "method": spec["clean_room_attestation"]["method"],
        "inventory_index": spec["scope"]["inventory_index"],
        "inventory_index_sha256": spec["scope"]["inventory_index_sha256"],
        "visual_direction": spec.get("visual_direction"),
        "art_direction": spec.get("art_direction"),
        "visual_generation": spec.get("visual_generation"),
        "visual_source_counts": _source_counts(manifest_entries),
        "generator": "tools/asset_generation/generate_full_inventory.py",
        "visual_generator": "tools/asset_generation/procedural_visuals.py",
        "audio_generator": "tools/asset_generation/procedural_audio.py",
        "ffmpeg_version": manifest["ffmpeg_version"],
        "manifest_sha256": sha256_file(os.path.join(root, "manifest.json")),
        "path_count": len(manifest_entries),
        "status": "candidate-not-active",
    }
    write_json(os.path.join(root, "provenance.json"), provenance)
    print(f"Generated {len(manifest_entries)} exact compatibility paths across {len(counts)} packs")
    return manifest


def _source_counts(entries):
    counts = {}
    for entry in entries:
        if entry.get("visual_source"):
            counts[entry["visual_source"]] = counts.get(entry["visual_source"], 0) + 1
    return dict(sorted(counts.items()))


def _jpeg_size(path):
    with open(path, "rb") as handle:
        if handle.read(2) != b"\xff\xd8":
            raise ValueError("missing JPEG SOI")
        while True:
            byte = handle.read(1)
            if not byte:
                break
            if byte != b"\xff":
                continue
            marker = handle.read(1)
            while marker == b"\xff":
                marker = handle.read(1)
            if marker in (b"\xd8", b"\xd9"):
                continue
            length_raw = handle.read(2)
            if len(length_raw) != 2:
                break
            length = struct.unpack(">H", length_raw)[0]
            if marker and marker[0] in range(0xC0, 0xC4):
                data = handle.read(5)
                return struct.unpack(">HH", data[1:5])[::-1]
            handle.seek(length - 2, os.SEEK_CUR)
    raise ValueError("JPEG has no supported SOF marker")


def _check_media(entry, path):
    extension = entry["extension"]
    if extension == ".png":
        image = read_png(path)
        if (image.width, image.height) != (entry["details"]["width"], entry["details"]["height"]):
            raise ValueError(f"PNG dimension mismatch for {entry['output']}")
        if entry["details"].get("indexed") and image.color_type != 3:
            raise ValueError(f"Expected indexed PNG for {entry['output']}")
    elif extension == ".jpg":
        if _jpeg_size(path) != (entry["details"]["width"], entry["details"]["height"]):
            raise ValueError(f"JPEG dimension mismatch for {entry['output']}")
    elif extension == ".ico":
        with open(path, "rb") as handle:
            if handle.read(6) != b"\x00\x00\x01\x00\x01\x00":
                raise ValueError(f"Invalid ICO header for {entry['output']}")
    else:
        signatures = {".mid": b"MThd", ".wav": b"RIFF", ".ogg": b"OggS"}
        with open(path, "rb") as handle:
            if handle.read(4) != signatures[extension]:
                raise ValueError(f"Invalid {extension} signature for {entry['output']}")


def verify(spec, plan):
    root = resolve_within(REPO_ROOT, spec["output_root"])
    manifest_path = os.path.join(root, "manifest.json")
    provenance_path = os.path.join(root, "provenance.json")
    with open(manifest_path, encoding="utf-8") as handle:
        manifest = json.load(handle)
    if manifest.get("path_count") != len(plan) or len(manifest.get("entries", [])) != len(plan):
        raise ValueError("Manifest path count does not match the complete generation plan")
    expected_keys = {(entry["pack"], entry["path"]) for entry in plan}
    actual_keys = {(entry["pack"], entry["path"]) for entry in manifest["entries"]}
    if actual_keys != expected_keys:
        raise ValueError("Manifest paths do not exactly cover the inventory plan")
    declared_outputs = set()
    for index, entry in enumerate(manifest["entries"], 1):
        path = resolve_within(root, entry["output"])
        declared_outputs.add(os.path.normpath(path))
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Missing generated asset: {entry['output']}")
        if sha256_file(path) != entry["sha256"]:
            raise ValueError(f"Hash mismatch for {entry['output']}")
        if os.path.getsize(path) != entry["bytes"]:
            raise ValueError(f"Byte-count mismatch for {entry['output']}")
        _check_media(entry, path)
        if index % 500 == 0:
            print(f"Verified {index}/{len(plan)} generated paths", flush=True)
    packs_root = os.path.join(root, "packs")
    disk_outputs = {
        os.path.normpath(os.path.join(directory, filename))
        for directory, _, filenames in os.walk(packs_root)
        for filename in filenames
    }
    extras = disk_outputs - declared_outputs
    if extras:
        raise ValueError(f"Generated pack contains undeclared files: {sorted(extras)[:5]}")
    if declared_outputs - disk_outputs:
        raise ValueError("Generated pack is missing declared files")
    with open(provenance_path, encoding="utf-8") as handle:
        provenance = json.load(handle)
    if provenance.get("manifest_sha256") != sha256_file(manifest_path):
        raise ValueError("Collection provenance does not bind the current manifest")
    if provenance.get("path_count") != len(plan):
        raise ValueError("Collection provenance path count mismatch")
    print(f"Full-inventory verification passed: {len(plan)} exact paths across {len(manifest['pack_counts'])} packs")
    return True


def main():
    parser = argparse.ArgumentParser(description="Generate or verify every clean-room compatibility asset")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--plan", action="store_true")
    action.add_argument("--write", action="store_true")
    action.add_argument("--check", action="store_true")
    parser.add_argument("--spec", default=SPEC_PATH, help="generation spec (v2 uses structured FLUX assets)")
    args = parser.parse_args()
    spec = load_spec(os.path.abspath(args.spec))
    plan = build_plan(spec)
    if args.plan:
        counts = {}
        for entry in plan:
            counts[entry["pack"]] = counts.get(entry["pack"], 0) + 1
        print(json.dumps({"paths": len(plan), "packs": dict(sorted(counts.items())),
                          "visuals": sum(entry["media"] == "visual" for entry in plan),
                          "audio": sum(entry["media"] == "audio" for entry in plan)}, indent=2))
    elif args.write:
        generate(spec, plan)
    else:
        verify(spec, plan)


if __name__ == "__main__":
    main()
