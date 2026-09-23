#!/usr/bin/env python3
"""
RPG Maker 2000/2003 ChipSet runtime verification through EasyRPG Player.

The fixture map (tests/fixtures/<target>_chipset_min) bundles no ChipSet and places
calibration tiles at map cells (2,2), (4,2), (6,2) and (8,2):
  - tile 5000  (Block E bank 1, lower layer)
  - tile 5096  (Block E bank 2, lower layer)
  - tile 10048 (Block F bank 2, upper layer)
  - tile 10000 (Block F bank 1, upper layer) drawn over tile 5000, so the lower tile's
    border and background must show through the upper tile's transparent corners.
Tile ids, bank coordinates and colors are documented in docs/architecture.md section 4.

Positive control resolves the ChipSet through the RTP alias the fixture requests
(Basis for rm2000, Main for rm2003); the negative control disables the RTP.

Usage:
  python3 tools/verify_chipset_runtime.py --target all --verify
  python3 tools/verify_chipset_runtime.py --target all --run-capture
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import easyrpg_runtime as easyrpg
import generate_calibration_chipset as gen
from build_target import build_target
from evidence import (check_file_hash, check_log, check_negative_control, check_screenshots, check_timestamp,
                      expect_field, load_evidence, require, write_evidence)
from png_utils import decode_png_rgb
from repo import evidence_timestamp, repo_path, sha256_file

CANONICAL_ASSET_ID = "test.calibration.map-chipset"
CANONICAL_SOURCE = repo_path("registry", "assets", "test_calibration_map_chipset.rgba")
REQUESTED_CHIPSET = {"rm2000": "Basis", "rm2003": "Main"}


# Calibration tile colors come from the generator that drew them (RGB only).
T5000 = {"center": gen.COLOR_5000_CENTER[:3], "border": gen.COLOR_5000_BORDER[:3], "bg": gen.COLOR_5000_BG[:3]}
T5096 = {"center": gen.COLOR_5096_CENTER[:3], "border": gen.COLOR_5096_BORDER[:3], "bg": gen.COLOR_5096_BG[:3]}
T10048_CENTER = gen.COLOR_10048_FG[:3]
T10000_CENTER = gen.COLOR_10000_FG[:3]

# Screen probes (x, y) at 2x scale: map cell (cx, cy) spans x = cx*32 .. cx*32+31.
PROBES = [
    ("Tile 5000 center", (80, 80), T5000["center"]),
    ("Tile 5000 border", (64, 64), T5000["border"]),
    ("Tile 5000 bg", (70, 70), T5000["bg"]),
    ("Tile 5096 center", (144, 80), T5096["center"]),
    ("Tile 5096 border", (128, 64), T5096["border"]),
    ("Tile 5096 bg", (134, 70), T5096["bg"]),
    ("Tile 10048 center", (208, 80), T10048_CENTER),
    ("Tile 10000 center", (272, 80), T10000_CENTER),
    ("Tile 10000/5000 composite corner", (256, 64), T5000["border"]),
    ("Tile 10000/5000 composite bg", (260, 68), T5000["bg"]),
]


def get_target_config(target="rm2000", artifacts_dir=None):
    target = "rm2003" if target in ("rm2003", "2k3") else "rm2000"
    artifacts_dir = artifacts_dir or repo_path("artifacts", "runtime", target, "chipset")
    return {
        "target": target,
        "engine": easyrpg.ENGINE_MODES[target],
        "expected_chipset_alias": REQUESTED_CHIPSET[target],
        "fixture_dir": repo_path("tests", "fixtures", f"{target}_chipset_min"),
        "target_dir": repo_path("generated", target),
        "artifacts_dir": artifacts_dir,
        "evidence_path": os.path.join(artifacts_dir, "verification_evidence.json"),
    }


def verify_chipset_screenshot(screenshot_path, mode="positive", target="rm2000"):
    """Checks tile colors and layer transparency in a 640x480 capture (mode: positive | negative_control)."""
    if not os.path.exists(screenshot_path):
        raise FileNotFoundError(f"Screenshot not found: {screenshot_path}")
    w, h, pixels = decode_png_rgb(screenshot_path)
    if (w, h) != (easyrpg.SCREEN_W, easyrpg.SCREEN_H):
        raise ValueError(f"Expected 640x480 screenshot, got {w}x{h}")

    if mode == "negative_control":
        easyrpg.require_warning_banner(pixels)
        center = pixels[80][80]
        if center == T5000["center"]:
            raise ValueError("Negative control unexpectedly rendered valid ChipSet tile 5000 at (80, 80)")
        return {"status": "VERIFIED", "mode": "negative_control", "missing_detected": True, "center_color": list(center)}

    observed = {}
    for label, (x, y), expected in PROBES:
        actual = pixels[y][x]
        if actual != expected:
            raise ValueError(f"{label} mismatch: expected {expected}, got {actual}")
        observed[label] = actual

    return {
        "status": "VERIFIED",
        "mode": "positive",
        "tile_5000": {"center": list(observed["Tile 5000 center"]), "border": list(observed["Tile 5000 border"]), "bg": list(observed["Tile 5000 bg"])},
        "tile_5096": {"center": list(observed["Tile 5096 center"]), "border": list(observed["Tile 5096 border"]), "bg": list(observed["Tile 5096 bg"])},
        "tile_10048": {"center": list(observed["Tile 10048 center"])},
        "tile_10000_over_5000": {
            "upper_center_cross": list(observed["Tile 10000 center"]),
            "lower_border_through_transparency": list(observed["Tile 10000/5000 composite corner"]),
            "lower_bg_through_transparency": list(observed["Tile 10000/5000 composite bg"]),
        },
    }


def verify_evidence_chain(target="rm2000", evidence_path=None, artifacts_dir=None, target_dir=None,
                          fixture_dir=None, canonical_rgba_path=None):
    """Verifies committed ChipSet evidence against the current files and re-inspects screenshots."""
    cfg = get_target_config(target, artifacts_dir)
    evidence_path = evidence_path or cfg["evidence_path"]
    artifacts_dir = cfg["artifacts_dir"]
    target_dir = target_dir or cfg["target_dir"]
    fixture_dir = fixture_dir or cfg["fixture_dir"]
    canonical_rgba_path = canonical_rgba_path or CANONICAL_SOURCE

    evidence = load_evidence(evidence_path)
    alias = cfg["expected_chipset_alias"]
    print(f"=== SuperRTP ChipSet Runtime Verification Evidence Check ({cfg['target']}) ===")
    print(f"Requested Slot:  {evidence.get('requested_chipset')}   EasyRPG: {evidence.get('easyrpg_version')}   Recorded: {evidence.get('recorded_at')}")

    expect_field(evidence, "target", cfg["target"], "Evidence target")
    expect_field(evidence, "engine_mode", cfg["engine"], "Evidence engine_mode")
    expect_field(evidence, "requested_chipset", alias, "Evidence requested_chipset")
    require(evidence.get("canonical_asset_id") == CANONICAL_ASSET_ID, f"Unexpected canonical_asset_id: {evidence.get('canonical_asset_id')}")
    check_file_hash(canonical_rgba_path, evidence.get("canonical_source_sha256"), "Canonical source SHA-256")
    easyrpg.check_pinned_version(evidence.get("easyrpg_version", ""))
    check_timestamp(evidence, "recorded_at")

    diagnostic = f"Image not found: ChipSet/{alias}"
    check_negative_control(evidence, f"ChipSet/{alias}", diagnostic)
    check_file_hash(os.path.join(target_dir, "manifest.json"), evidence.get("target_manifest_sha256"), "Target manifest hash")
    check_file_hash(os.path.join(target_dir, "ChipSet", "World.png"), evidence.get("target_world_sha256"), "Target World.png hash")
    check_file_hash(os.path.join(fixture_dir, "fixture_manifest.json"), evidence.get("fixture_manifest_sha256"), "Fixture manifest hash")
    check_log(artifacts_dir, evidence, "positive")
    check_log(artifacts_dir, evidence, "negative", required_text=[diagnostic])

    results = {}

    def inspect(name, path):
        mode = "negative_control" if "negative" in name else "positive"
        results[mode] = verify_chipset_screenshot(path, mode=mode, target=cfg["target"])
        return "Visual content: " + results[mode]["status"]

    check_screenshots(artifacts_dir, evidence.get("screenshots", {}), inspect)
    require(evidence.get("tile_evidence") == results.get("positive"), "tile_evidence does not match the re-inspected positive screenshot")
    print(f"ALL CHIPSET RUNTIME EVIDENCE CHECKS PASSED ({cfg['target']}): Evidence chain is durable and verified.")
    return True


def run_capture_and_record(target="rm2000", artifacts_dir=None):
    """Runs live positive and negative EasyRPG sessions, inspects the captures and writes evidence."""
    cfg = get_target_config(target, artifacts_dir)
    player = easyrpg.find_player()
    version = easyrpg.player_version(player)
    easyrpg.check_pinned_version(version)
    build_target(cfg["target"], output_dir=cfg["target_dir"], clean=True)
    os.makedirs(cfg["artifacts_dir"], exist_ok=True)

    alias = cfg["expected_chipset_alias"]
    pos_log = os.path.join(cfg["artifacts_dir"], "positive_runtime.log")
    neg_log = os.path.join(cfg["artifacts_dir"], "negative_runtime.log")
    pos_name = f"{cfg['target']}_chipset_positive.png"
    neg_name = f"{cfg['target']}_chipset_negative_control.png"
    pos_path = os.path.join(cfg["artifacts_dir"], pos_name)
    neg_path = os.path.join(cfg["artifacts_dir"], neg_name)

    print(f"Executing EasyRPG positive control for {cfg['target']} under Xvfb...")
    command = easyrpg.player_command(player, cfg["fixture_dir"], cfg["engine"], rtp_dir=cfg["target_dir"], log_file=pos_log)
    with easyrpg.session(command, log_file=pos_log) as display:
        easyrpg.wait_for(display, lambda png: bool(verify_chipset_screenshot(png, "positive", cfg["target"])), pos_path)
    print(f"Executing EasyRPG negative control for {cfg['target']} under Xvfb...")
    with easyrpg.session(easyrpg.player_command(player, cfg["fixture_dir"], cfg["engine"], log_file=neg_log), log_file=neg_log) as display:
        easyrpg.wait_for(display, lambda png: bool(verify_chipset_screenshot(png, "negative_control", cfg["target"])), neg_path)

    pos_vis = verify_chipset_screenshot(pos_path, mode="positive", target=cfg["target"])
    verify_chipset_screenshot(neg_path, mode="negative_control", target=cfg["target"])
    diagnostic = f"Image not found: ChipSet/{alias}"
    with open(neg_log, "r", encoding="utf-8", errors="replace") as f:
        if diagnostic not in f.read():
            raise ValueError(f"Negative control log does not contain '{diagnostic}'")

    shots = {pos_name: sha256_file(pos_path), neg_name: sha256_file(neg_path)}
    evidence = {
        "target": cfg["target"],
        "engine_mode": cfg["engine"],
        "requested_chipset": alias,
        "canonical_asset_id": CANONICAL_ASSET_ID,
        "canonical_source_sha256": sha256_file(CANONICAL_SOURCE),
        "target_manifest_sha256": sha256_file(os.path.join(cfg["target_dir"], "manifest.json")),
        "target_world_sha256": sha256_file(os.path.join(cfg["target_dir"], "ChipSet", "World.png")),
        "fixture_manifest_sha256": sha256_file(os.path.join(cfg["fixture_dir"], "fixture_manifest.json")),
        "positive_runtime_log": "positive_runtime.log",
        "positive_runtime_log_sha256": sha256_file(pos_log),
        "negative_runtime_log": "negative_runtime.log",
        "negative_runtime_log_sha256": sha256_file(neg_log),
        "easyrpg_version": version,
        "recorded_at": evidence_timestamp(),
        "negative_control": {
            "status": "VERIFIED",
            "expected_missing_asset": f"ChipSet/{alias}",
            "diagnostic": diagnostic,
            "screenshot": neg_name,
            "screenshot_sha256": shots[neg_name],
        },
        "screenshots": shots,
        "tile_evidence": pos_vis,
    }
    write_evidence(cfg["evidence_path"], evidence)
    return True


def main():
    parser = argparse.ArgumentParser(description="SuperRTP RM2000/RM2003 ChipSet runtime verifier (EasyRPG Player)")
    parser.add_argument("--target", choices=["rm2000", "rm2003", "all"], default="all")
    parser.add_argument("--verify", action="store_true", help="Verify committed evidence (default action)")
    parser.add_argument("--run-capture", action="store_true", help="Re-capture with live EasyRPG Player first")
    parser.add_argument("--artifacts-dir", default=None, help="Use DIR/<target> instead of artifacts/runtime/<target>/chipset")
    args = parser.parse_args()

    targets = ["rm2000", "rm2003"] if args.target == "all" else [args.target]
    for t in targets:
        artifacts_dir = os.path.join(os.path.abspath(args.artifacts_dir), t) if args.artifacts_dir else None
        if args.run_capture:
            run_capture_and_record(t, artifacts_dir)
        verify_evidence_chain(t, artifacts_dir=artifacts_dir)


if __name__ == "__main__":
    main()
