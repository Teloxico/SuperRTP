#!/usr/bin/env python3
"""
RPG Maker XP (RGSS1) character runtime verification through mkxp-z.

Fixture tests/fixtures/rmxp_character_min/fixture.rb draws a 640x480 scene: dark
background, a light test pad at (260, 164, 120x152) with colored corner markers, and the
96x128 sheet Graphics/Characters/001-Fighter01 loaded through the RTP at (272, 176).

Positive control (RTP = generated/rmxp): exit code 0, and the captured sheet must match
the generated PNG pixel for pixel, with arrows and step feet where RMXP_LAYOUT puts them.
Negative control (empty RTP): exit code 1 with SUPERRTP_RMXP_MISSING_ASSET and a blank pad.

Usage:
  python3 tools/verify_rmxp_runtime.py --verify
  python3 tools/verify_rmxp_runtime.py --run-capture
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mkxp_runtime as mkxp
from build_target import build_target
from evidence import (check_file_hash, check_log, check_negative_control, check_screenshots, check_timestamp,
                      config_sha256, expect_field, load_evidence, require, write_evidence)
from generate_calibration_charset import SLOT_THEMES
from png_utils import decode_png_rgb, read_png
from registry import load_slot_mapping
from repo import evidence_timestamp, repo_path, sha256_file
from screen_checks import (ARROW_PROBES, CELL_H, CELL_W, STEP_FOOT_PROBES, check_composite, check_markers, check_screen_arrows,
                           rgb_at)
from transforms import RMXP_LAYOUT

PINNED_MKXP_COMMIT = mkxp.PINNED_MKXP_COMMIT
CANONICAL_ASSET_ID = "test.calibration.walking-character"
CANONICAL_SOURCE = repo_path("registry", "assets", "test_calibration_walking_character.rgba")
SLOT = "Graphics/Characters/001-Fighter01.png"
REQUESTED = "Graphics/Characters/001-Fighter01"
DIAGNOSTIC = f"SUPERRTP_RMXP_MISSING_ASSET: No such file or directory - {REQUESTED}"
FIXTURE_REL = "tests/fixtures/rmxp_character_min"

# Scene geometry drawn by fixture.rb.
BACKGROUND = (25, 25, 30)
PAD = (210, 215, 220)
SHEET_ORIGIN = (272, 176)
SCENE_MARKERS = [
    ("Pad TL corner marker", (262, 166), (255, 60, 60)),
    ("Pad TR corner marker", (374, 166), (60, 255, 60)),
    ("Pad BL corner marker", (262, 310), (60, 60, 255)),
    ("Pad BR corner marker", (374, 310), (255, 255, 60)),
    ("Background color", (50, 50), BACKGROUND),
]
THEME = SLOT_THEMES[0]  # the RMXP sheet is canonical character 0
IDLE_COLUMNS = [i for i, phase in enumerate(RMXP_LAYOUT.columns) if phase == "IDLE"]


def get_target_config(artifacts_dir=None):
    artifacts_dir = artifacts_dir or repo_path("artifacts", "runtime", "rmxp", "character")
    return {
        "target": "rmxp",
        "engine": "rgss1",
        "expected_character_slot": "001-Fighter01",
        "fixture_dir": repo_path(FIXTURE_REL),
        "target_dir": repo_path("generated", "rmxp"),
        "artifacts_dir": artifacts_dir,
        "evidence_path": os.path.join(artifacts_dir, "verification_evidence.json"),
    }


def scene_drawn(frame: bytes, with_sheet: bool) -> bool:
    """Classifier for raw RGB24 samples: pad drawn and, for the positive control, the first idle arrow tip too."""
    (_, (mx, my), marker), width = SCENE_MARKERS[0], mkxp.SCREEN_SIZES[1][0]
    if rgb_at(frame, width, mx, my) != marker:
        return False
    if not with_sheet:
        return True
    (tx, ty), _, _, _ = ARROW_PROBES[RMXP_LAYOUT.rows[0]]
    return rgb_at(frame, width, SHEET_ORIGIN[0] + IDLE_COLUMNS[0] * CELL_W + tx, SHEET_ORIGIN[1] + ty) == THEME["outline"]


def _transform_policy() -> str:
    return load_slot_mapping("rmxp")["slots"][SLOT]["transform_policy"]


def verify_rmxp_screenshot(screenshot_path, mode="positive", target_char_path=None):
    """Checks a 640x480 capture (mode: positive | negative_control)."""
    if not os.path.exists(screenshot_path):
        raise FileNotFoundError(f"Screenshot not found: {screenshot_path}")
    w, h, pixels = decode_png_rgb(screenshot_path)
    if (w, h) != mkxp.SCREEN_SIZES[1]:
        raise ValueError(f"Expected 640x480 screenshot, got {w}x{h}")
    check_markers(pixels, SCENE_MARKERS)
    x0, y0 = SHEET_ORIGIN

    if mode == "negative_control":
        # Nothing may be drawn where the sheet would be: every idle arrow tip shows the pad.
        for column in IDLE_COLUMNS:
            try:
                check_screen_arrows(pixels, x0, y0, RMXP_LAYOUT.rows, column, PAD, PAD)
            except ValueError as exc:
                raise ValueError(f"Negative control unexpectedly rendered character sprite: {exc}") from exc
        return {"status": "VERIFIED", "mode": "negative_control", "missing_detected": True}

    sheet = read_png(target_char_path or os.path.join(get_target_config()["target_dir"], SLOT))
    check_composite(pixels, sheet.rgba_bytes(), sheet.width, sheet.height, x0, y0, PAD, label="XP sheet")
    for column in IDLE_COLUMNS:
        check_screen_arrows(pixels, x0, y0, RMXP_LAYOUT.rows, column, THEME["outline"], PAD)
    first = IDLE_COLUMNS[0]
    for column in IDLE_COLUMNS[1:]:
        for y in range(y0, y0 + sheet.height):
            a = pixels[y][x0 + first * CELL_W:x0 + (first + 1) * CELL_W]
            b = pixels[y][x0 + column * CELL_W:x0 + (column + 1) * CELL_W]
            if a != b:
                raise ValueError(f"XP idle column {column} differs from idle column {first} at y={y}")
    for column, phase in enumerate(RMXP_LAYOUT.columns):
        if phase in STEP_FOOT_PROBES:
            fx, fy = STEP_FOOT_PROBES[phase]
            for row in range(len(RMXP_LAYOUT.rows)):
                x, y = x0 + column * CELL_W + fx, y0 + row * CELL_H + fy
                if pixels[y][x] != THEME["foot"]:
                    raise ValueError(f"Row {row} Col {column} ({phase}) foot marker mismatch at ({x}, {y}): expected {THEME['foot']}, got {pixels[y][x]}")
    return {"status": "VERIFIED", "mode": "positive", "composite_equality": "100% match across 96x128",
            "columns": list(RMXP_LAYOUT.columns), "rows": list(RMXP_LAYOUT.rows)}


def verify_evidence_chain(evidence_path=None, artifacts_dir=None, target_dir=None, fixture_dir=None, canonical_rgba_path=None):
    """Verifies committed RMXP evidence against the current files and re-inspects screenshots."""
    cfg = get_target_config(artifacts_dir)
    evidence = load_evidence(evidence_path or cfg["evidence_path"])
    artifacts_dir = cfg["artifacts_dir"]
    target_dir = target_dir or cfg["target_dir"]
    fixture_dir = fixture_dir or cfg["fixture_dir"]
    print("=== SuperRTP RPG Maker XP Character Runtime Verification Evidence Check ===")
    print(f"mkxp-z: {evidence.get('mkxp_z_version')}   Policy: {evidence.get('transform_policy')}   Recorded: {evidence.get('recorded_at')}")

    expect_field(evidence, "target", "rmxp", "Evidence target")
    expect_field(evidence, "engine", "RPG Maker XP", "Evidence engine")
    expect_field(evidence, "engine_mode", "rgss1", "Evidence engine_mode")
    expect_field(evidence, "runtime", "mkxp-z", "Evidence runtime")
    require(evidence.get("runtime_commit") == PINNED_MKXP_COMMIT,
            f"mkxp-z commit pin violation: expected '{PINNED_MKXP_COMMIT}', got '{evidence.get('runtime_commit')}'")
    require(PINNED_MKXP_COMMIT[:7] in str(evidence.get("mkxp_z_version", "")),
            f"mkxp-z version string violation: expected {PINNED_MKXP_COMMIT[:7]} in '{evidence.get('mkxp_z_version')}'")
    expect_field(evidence, "rgss_version", 1, "Evidence rgss_version")
    expect_field(evidence, "target_category", "Character", "Evidence target_category")
    expect_field(evidence, "requested_resource", REQUESTED, "Evidence requested_resource")
    expect_field(evidence, "source_character_index", 0, "Evidence source_character_index")
    expect_field(evidence, "transform_policy", _transform_policy(), "Evidence transform_policy")
    mkxp.check_build_configuration(evidence.get("mkxp_z_build_configuration"))
    expect_field(evidence, "positive_exit_code", 0, "positive_exit_code")
    expect_field(evidence, "negative_exit_code", 1, "negative_exit_code")
    require(evidence.get("canonical_asset_id") == CANONICAL_ASSET_ID, f"Unexpected canonical_asset_id: {evidence.get('canonical_asset_id')}")
    check_file_hash(canonical_rgba_path or CANONICAL_SOURCE, evidence.get("canonical_source_sha256"), "Canonical source SHA-256")
    check_timestamp(evidence, "recorded_at")
    check_negative_control(evidence, REQUESTED, DIAGNOSTIC)

    check_file_hash(os.path.join(target_dir, "manifest.json"), evidence.get("target_manifest_sha256"), "Target manifest hash")
    target_char = os.path.join(target_dir, SLOT)
    check_file_hash(target_char, evidence.get("target_character_sha256"), "Target character file hash")
    check_file_hash(os.path.join(fixture_dir, "fixture_manifest.json"), evidence.get("fixture_manifest_sha256"), "Fixture manifest hash")
    expect_field(evidence, "fixture_script", "fixture.rb", "Evidence fixture_script")
    check_file_hash(os.path.join(fixture_dir, "fixture.rb"), evidence.get("fixture_script_sha256"), "Fixture script hash")
    for kind, rtp in (("positive", ["generated/rmxp"]), ("negative", [])):
        conf = evidence.get(f"{kind}_runtime_configuration")
        mkxp.check_portable_config(conf, 1, FIXTURE_REL, rtp, f"{kind.capitalize()} runtime configuration")
        require(config_sha256(conf, indent=2) == evidence.get(f"{kind}_runtime_configuration_sha256"),
                f"{kind.capitalize()} runtime configuration hash mismatch")

    check_log(artifacts_dir, evidence, "positive", required_text=["SUPERRTP_RMXP_CHARACTER_LOADED 96x128", "SUPERRTP_RMXP_RENDER_DONE"])
    check_log(artifacts_dir, evidence, "negative", required_text=[DIAGNOSTIC])

    results = {}

    def inspect(name, path):
        mode = "negative_control" if "negative" in name else "positive"
        results[mode] = verify_rmxp_screenshot(path, mode=mode, target_char_path=target_char)
        return "Visual content: " + results[mode]["status"]

    check_screenshots(artifacts_dir, evidence.get("screenshots", {}), inspect)
    require(evidence.get("visual_evidence") == results.get("positive"), "visual_evidence does not match the re-inspected positive screenshot")
    print("ALL RPG MAKER XP CHARACTER RUNTIME EVIDENCE CHECKS PASSED: Evidence chain is durable and verified.")
    return True


def run_capture_and_record(artifacts_dir=None):
    """Runs live positive and negative mkxp-z sessions, inspects the captures and writes evidence."""
    cfg = get_target_config(artifacts_dir)
    mkxp_bin = mkxp.find_mkxp()
    build_meta = mkxp.read_build_metadata(mkxp_bin)
    build_target("rmxp", output_dir=cfg["target_dir"], clean=True)
    os.makedirs(cfg["artifacts_dir"], exist_ok=True)

    pos_conf = mkxp.portable_config(1, FIXTURE_REL, ["generated/rmxp"])
    neg_conf = mkxp.portable_config(1, FIXTURE_REL, [])
    pos_name, neg_name = "rmxp_character_positive.png", "rmxp_character_negative_control.png"
    pos_path = os.path.join(cfg["artifacts_dir"], pos_name)
    neg_path = os.path.join(cfg["artifacts_dir"], neg_name)

    print("Executing mkxp-z RGSS1 positive control under Xvfb...")
    pos = mkxp.run_session(mkxp_bin, pos_conf, pos_path, mkxp.POSITIVE_RECORD_SECONDS, lambda f: scene_drawn(f, True))
    if pos.exit_code != 0:
        raise RuntimeError(f"Positive control mkxp-z failed with exit code {pos.exit_code}:\n{pos.log}")
    print("Executing mkxp-z RGSS1 negative control under Xvfb...")
    neg = mkxp.run_session(mkxp_bin, neg_conf, neg_path, mkxp.NEGATIVE_RECORD_SECONDS, lambda f: scene_drawn(f, False))
    if neg.exit_code != 1:
        raise RuntimeError(f"Negative control mkxp-z expected exit code 1, got {neg.exit_code}:\n{neg.log}")

    logs = {}
    for kind, run in (("positive", pos), ("negative", neg)):
        logs[kind] = os.path.join(cfg["artifacts_dir"], f"{kind}_runtime.log")
        with open(logs[kind], "w", encoding="utf-8") as f:
            f.write(run.log)

    target_char = os.path.join(cfg["target_dir"], SLOT)
    pos_vis = verify_rmxp_screenshot(pos_path, mode="positive", target_char_path=target_char)
    verify_rmxp_screenshot(neg_path, mode="negative_control")
    shots = {pos_name: sha256_file(pos_path), neg_name: sha256_file(neg_path)}

    evidence = {
        "target": "rmxp",
        "engine": "RPG Maker XP",
        "engine_mode": "rgss1",
        "runtime": "mkxp-z",
        "runtime_commit": PINNED_MKXP_COMMIT,
        "rgss_version": 1,
        "target_category": "Character",
        "requested_resource": REQUESTED,
        "source_character_index": 0,
        "transform_policy": _transform_policy(),
        "mkxp_z_build_configuration": mkxp.build_configuration_summary(build_meta),
        "canonical_asset_id": CANONICAL_ASSET_ID,
        "canonical_source_sha256": sha256_file(CANONICAL_SOURCE),
        "target_manifest_sha256": sha256_file(os.path.join(cfg["target_dir"], "manifest.json")),
        "target_character_sha256": sha256_file(target_char),
        "fixture_manifest_sha256": sha256_file(os.path.join(cfg["fixture_dir"], "fixture_manifest.json")),
        "fixture_script": "fixture.rb",
        "fixture_script_sha256": sha256_file(os.path.join(cfg["fixture_dir"], "fixture.rb")),
        "positive_runtime_configuration": pos_conf,
        "positive_runtime_configuration_sha256": config_sha256(pos_conf, indent=2),
        "negative_runtime_configuration": neg_conf,
        "negative_runtime_configuration_sha256": config_sha256(neg_conf, indent=2),
        "positive_exit_code": pos.exit_code,
        "negative_exit_code": neg.exit_code,
        "positive_runtime_log": "positive_runtime.log",
        "positive_runtime_log_sha256": sha256_file(logs["positive"]),
        "negative_runtime_log": "negative_runtime.log",
        "negative_runtime_log_sha256": sha256_file(logs["negative"]),
        "mkxp_z_version": pos.version,
        "recorded_at": evidence_timestamp(),
        "negative_control": {
            "status": "VERIFIED",
            "expected_missing_asset": REQUESTED,
            "diagnostic": DIAGNOSTIC,
            "screenshot": neg_name,
            "screenshot_sha256": shots[neg_name],
        },
        "screenshots": shots,
        "visual_evidence": pos_vis,
    }
    write_evidence(cfg["evidence_path"], evidence)
    return True


def main():
    parser = argparse.ArgumentParser(description="SuperRTP RPG Maker XP character runtime verifier (mkxp-z)")
    parser.add_argument("--verify", action="store_true", help="Verify committed evidence (default action)")
    parser.add_argument("--run-capture", action="store_true", help="Re-capture with live mkxp-z first")
    parser.add_argument("--artifacts-dir", default=None, help="Use DIR instead of artifacts/runtime/rmxp/character")
    args = parser.parse_args()
    artifacts_dir = os.path.abspath(args.artifacts_dir) if args.artifacts_dir else None
    if args.run_capture:
        run_capture_and_record(artifacts_dir)
    verify_evidence_chain(artifacts_dir=artifacts_dir)


if __name__ == "__main__":
    main()
