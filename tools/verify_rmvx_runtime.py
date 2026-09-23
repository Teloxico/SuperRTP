#!/usr/bin/env python3
"""
RPG Maker VX (RGSS2) character runtime verification through mkxp-z, plus the capture and
screenshot checks shared with RPG Maker VX Ace (tools/verify_rmvxace_runtime.py).

Fixture tests/fixtures/rmvx_character_min/fixture.rb (the VX Ace fixture is the same
scene in RGSS3) draws a 544x416 scene: dark background, a light test pad at
(116, 68, 312x280) with colored corner markers, and the 288x256 standard 8-character
sheet Graphics/Characters/Actor1 loaded through the RTP at (128, 80).

Positive control: exit code 0 and a pixel-exact composite of the generated sheet, with
every character block's idle arrows in the row order of VX_FAMILY_LAYOUT.
Negative control (empty RTP): exit code 1, SUPERRTP_RMVX_MISSING_ASSET, and a blank pad.

Usage:
  python3 tools/verify_rmvx_runtime.py --verify
  python3 tools/verify_rmvx_runtime.py --run-capture
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
from screen_checks import ARROW_PROBES, check_composite, check_markers, check_screen_arrows, rgb_at
from transforms import VX_FAMILY_LAYOUT

PINNED_MKXP_COMMIT = mkxp.PINNED_MKXP_COMMIT
CANONICAL_ASSET_ID = "test.calibration.walking-character"
CANONICAL_SOURCE = repo_path("registry", "assets", "test_calibration_walking_character.rgba")
SLOT = "Graphics/Characters/Actor1.png"
REQUESTED = "Graphics/Characters/Actor1"
FIXTURE_REL = "tests/fixtures/rmvx_character_min"
DIAGNOSTIC = f"SUPERRTP_RMVX_MISSING_ASSET: No such file or directory - {REQUESTED}"

# Scene geometry shared by the VX and VX Ace fixtures.
BACKGROUND = (25, 25, 30)
PAD = (210, 215, 220)
SHEET_ORIGIN = (128, 80)
SCENE_MARKERS = [
    ("Pad TL corner marker", (118, 70), (255, 60, 60)),
    ("Pad TR corner marker", (422, 70), (60, 255, 60)),
    ("Pad BL corner marker", (118, 342), (60, 60, 255)),
    ("Pad BR corner marker", (422, 342), (255, 255, 60)),
    ("Background color", (30, 30), BACKGROUND),
]
IDLE_COLUMN = VX_FAMILY_LAYOUT.columns.index("IDLE")


def get_target_config(artifacts_dir=None):
    artifacts_dir = artifacts_dir or repo_path("artifacts", "runtime", "rmvx", "character")
    return {
        "target": "rmvx",
        "engine": "rgss2",
        "expected_character_slot": "Actor1",
        "fixture_dir": repo_path(FIXTURE_REL),
        "target_dir": repo_path("generated", "rmvx"),
        "artifacts_dir": artifacts_dir,
        "evidence_path": os.path.join(artifacts_dir, "verification_evidence.json"),
    }


def _block_origin(char_idx):
    width, height = 3 * 24, 4 * 32
    return (SHEET_ORIGIN[0] + (char_idx % VX_FAMILY_LAYOUT.characters_across) * width,
            SHEET_ORIGIN[1] + (char_idx // VX_FAMILY_LAYOUT.characters_across) * height)


def scene_drawn(frame: bytes, with_sheet: bool) -> bool:
    """Classifier for raw RGB24 samples: pad drawn and, for the positive control, block 0's first idle arrow tip too."""
    (_, (mx, my), marker), width = SCENE_MARKERS[0], mkxp.SCREEN_SIZES[2][0]
    if rgb_at(frame, width, mx, my) != marker:
        return False
    if not with_sheet:
        return True
    (tx, ty), _, _, _ = ARROW_PROBES[VX_FAMILY_LAYOUT.rows[0]]
    bx, by = _block_origin(0)
    return rgb_at(frame, width, bx + IDLE_COLUMN * 24 + tx, by + ty) == SLOT_THEMES[0]["outline"]


def verify_vx_family_screenshot(screenshot_path, target_char_path=None, mode="positive"):
    """Checks a 544x416 VX/VX Ace capture (mode: positive | negative_control)."""
    if not os.path.exists(screenshot_path):
        raise FileNotFoundError(f"Screenshot not found: {screenshot_path}")
    w, h, pixels = decode_png_rgb(screenshot_path)
    if (w, h) != mkxp.SCREEN_SIZES[2]:
        raise ValueError(f"Expected 544x416 screenshot, got {w}x{h}")
    check_markers(pixels, SCENE_MARKERS)

    if mode == "negative_control":
        for char_idx in range(VX_FAMILY_LAYOUT.character_count):
            try:
                check_screen_arrows(pixels, *_block_origin(char_idx), VX_FAMILY_LAYOUT.rows, IDLE_COLUMN, PAD, PAD, f"Block {char_idx} ")
            except ValueError as exc:
                raise ValueError(f"Negative control expected blank pad color {PAD}: {exc}") from exc
        return {"status": "VERIFIED", "mode": "negative_control", "screenshot_dimensions": "544x416", "pad_blank": "VERIFIED"}

    sheet = read_png(target_char_path or os.path.join(get_target_config()["target_dir"], SLOT))
    if (sheet.width, sheet.height) != VX_FAMILY_LAYOUT.size():
        raise ValueError(f"Target character dimensions mismatch: expected 288x256, got {sheet.width}x{sheet.height}")
    check_composite(pixels, sheet.rgba_bytes(), sheet.width, sheet.height, *SHEET_ORIGIN, PAD, label="VX sheet")
    for char_idx in range(VX_FAMILY_LAYOUT.character_count):
        check_screen_arrows(pixels, *_block_origin(char_idx), VX_FAMILY_LAYOUT.rows, IDLE_COLUMN,
                            SLOT_THEMES[char_idx]["outline"], PAD, f"Block {char_idx} ")
    return {"status": "VERIFIED", "mode": "positive", "screenshot_dimensions": "544x416",
            "composite_equality": "100% pixel match across 288x256 region",
            "all_8_character_blocks": "VERIFIED (idle arrows DOWN/LEFT/RIGHT/UP in every block)"}



class VxCapture:
    """Everything a live VX-family capture produced, for building target-specific evidence."""

    def __init__(self, **fields):
        self.__dict__.update(fields)


def capture_vx_family(target: str, rgss_version: int, fixture_rel: str, marker_prefix: str, artifacts_dir: str) -> VxCapture:
    """
    Builds `target`, runs positive and negative mkxp-z sessions, writes logs and screenshots
    into `artifacts_dir`, and checks exit codes, log markers and pixels.
    """
    mkxp_bin = mkxp.find_mkxp()
    build_meta = mkxp.read_build_metadata(mkxp_bin)
    target_dir = repo_path("generated", target)
    build_target(target, output_dir=target_dir, clean=True)
    os.makedirs(artifacts_dir, exist_ok=True)

    pos_conf = mkxp.portable_config(rgss_version, fixture_rel, [f"generated/{target}"])
    neg_conf = mkxp.portable_config(rgss_version, fixture_rel, [])
    pos_path = os.path.join(artifacts_dir, f"{target}_character_positive.png")
    neg_path = os.path.join(artifacts_dir, f"{target}_character_negative_control.png")

    print(f"Executing mkxp-z RGSS{rgss_version} positive control under Xvfb...")
    pos = mkxp.run_session(mkxp_bin, pos_conf, pos_path, mkxp.POSITIVE_RECORD_SECONDS, lambda f: scene_drawn(f, True))
    if pos.exit_code != 0:
        raise RuntimeError(f"Positive control mkxp-z failed with exit code {pos.exit_code}:\n{pos.log}")
    for marker in (f"SUPERRTP_RGSS{rgss_version}_SCREEN 544x416", f"SUPERRTP_{marker_prefix}_CHARACTER_LOADED 288x256",
                   f"SUPERRTP_{marker_prefix}_RENDER_DONE"):
        if marker not in pos.stdout:
            raise ValueError(f"Positive log missing expected marker '{marker}'")

    print(f"Executing mkxp-z RGSS{rgss_version} negative control under Xvfb...")
    neg = mkxp.run_session(mkxp_bin, neg_conf, neg_path, mkxp.NEGATIVE_RECORD_SECONDS, lambda f: scene_drawn(f, False))
    if neg.exit_code != 1:
        raise RuntimeError(f"Negative control mkxp-z expected exit code 1 (missing asset), got {neg.exit_code}:\n{neg.log}")

    logs = {}
    for kind, run in (("positive", pos), ("negative", neg)):
        logs[kind] = os.path.join(artifacts_dir, f"{kind}_runtime.log")
        with open(logs[kind], "w", encoding="utf-8") as f:
            f.write(run.log)

    target_char = os.path.join(target_dir, SLOT)
    pos_vis = verify_vx_family_screenshot(pos_path, target_char_path=target_char, mode="positive")
    neg_vis = verify_vx_family_screenshot(neg_path, mode="negative_control")
    return VxCapture(build_meta=build_meta, pos=pos, neg=neg, pos_conf=pos_conf, neg_conf=neg_conf,
                     pos_path=pos_path, neg_path=neg_path, logs=logs, target_dir=target_dir,
                     target_char=target_char, pos_vis=pos_vis, neg_vis=neg_vis)


def _transform_policy() -> str:
    return load_slot_mapping("rmvx")["slots"][SLOT]["transform_policy"]


def run_capture(cfg=None):
    """Live RMVX capture; writes artifacts/runtime/rmvx/character/verification_evidence.json."""
    cfg = cfg or get_target_config()
    cap = capture_vx_family("rmvx", 2, FIXTURE_REL, "RMVX", cfg["artifacts_dir"])
    pos_name, neg_name = os.path.basename(cap.pos_path), os.path.basename(cap.neg_path)
    shots = {pos_name: sha256_file(cap.pos_path), neg_name: sha256_file(cap.neg_path)}
    evidence = {
        "target": "rmvx",
        "engine": "RPG Maker VX",
        "engine_mode": "rgss2",
        "runtime": "mkxp-z",
        "runtime_commit": PINNED_MKXP_COMMIT,
        "rgss_version": 2,
        "target_category": "Character",
        "requested_resource": REQUESTED,
        "source_character_indices": list(range(8)),
        "transform_policy": _transform_policy(),
        "mkxp_z_build_configuration": mkxp.build_configuration_summary(cap.build_meta),
        "canonical_asset_id": CANONICAL_ASSET_ID,
        "canonical_source_sha256": sha256_file(CANONICAL_SOURCE),
        "target_manifest_sha256": sha256_file(os.path.join(cap.target_dir, "manifest.json")),
        "target_character_sha256": sha256_file(cap.target_char),
        "fixture_manifest_sha256": sha256_file(os.path.join(cfg["fixture_dir"], "fixture_manifest.json")),
        "fixture_script": "fixture.rb",
        "fixture_script_sha256": sha256_file(os.path.join(cfg["fixture_dir"], "fixture.rb")),
        "positive_runtime_configuration": cap.pos_conf,
        "positive_runtime_configuration_sha256": config_sha256(cap.pos_conf, indent=2),
        "negative_runtime_configuration": cap.neg_conf,
        "negative_runtime_configuration_sha256": config_sha256(cap.neg_conf, indent=2),
        "positive_exit_code": cap.pos.exit_code,
        "negative_exit_code": cap.neg.exit_code,
        "positive_runtime_log": "positive_runtime.log",
        "positive_runtime_log_sha256": sha256_file(cap.logs["positive"]),
        "negative_runtime_log": "negative_runtime.log",
        "negative_runtime_log_sha256": sha256_file(cap.logs["negative"]),
        "mkxp_z_version": cap.pos.version,
        "recorded_at": evidence_timestamp(),
        "negative_control": {
            "status": "VERIFIED",
            "expected_missing_asset": REQUESTED,
            "diagnostic": DIAGNOSTIC,
            "screenshot": neg_name,
            "screenshot_sha256": shots[neg_name],
        },
        "screenshots": shots,
        "visual_verification": {"positive_control": cap.pos_vis, "negative_control": cap.neg_vis},
    }
    write_evidence(cfg["evidence_path"], evidence)
    return evidence


def verify_evidence_chain(evidence_path=None, cfg=None, artifacts_dir=None):
    """Verifies RMVX evidence against the current files and re-inspects screenshots."""
    cfg = cfg or get_target_config(artifacts_dir)
    evidence = load_evidence(evidence_path or cfg["evidence_path"])
    expect_field(evidence, "target", "rmvx", "Evidence target")
    expect_field(evidence, "engine", "RPG Maker VX", "Evidence engine")
    expect_field(evidence, "engine_mode", "rgss2", "Evidence engine_mode")
    expect_field(evidence, "runtime", "mkxp-z", "Evidence runtime")
    require(evidence.get("runtime_commit") == PINNED_MKXP_COMMIT,
            f"mkxp-z commit pin violation: expected '{PINNED_MKXP_COMMIT}', got '{evidence.get('runtime_commit')}'")
    require(PINNED_MKXP_COMMIT[:7] in str(evidence.get("mkxp_z_version", "")),
            f"mkxp-z version string violation: expected {PINNED_MKXP_COMMIT[:7]} in '{evidence.get('mkxp_z_version')}'")
    expect_field(evidence, "rgss_version", 2, "Evidence rgss_version")
    expect_field(evidence, "target_category", "Character", "Evidence target_category")
    expect_field(evidence, "requested_resource", REQUESTED, "Evidence requested_resource")
    expect_field(evidence, "source_character_indices", list(range(8)), "Evidence source_character_indices")
    expect_field(evidence, "transform_policy", _transform_policy(), "Evidence transform_policy")
    mkxp.check_build_configuration(evidence.get("mkxp_z_build_configuration"))
    expect_field(evidence, "positive_exit_code", 0, "positive_exit_code")
    expect_field(evidence, "negative_exit_code", 1, "negative_exit_code")
    require(evidence.get("canonical_asset_id") == CANONICAL_ASSET_ID, f"Unexpected canonical_asset_id: {evidence.get('canonical_asset_id')}")
    check_file_hash(CANONICAL_SOURCE, evidence.get("canonical_source_sha256"), "Canonical source SHA-256")
    check_timestamp(evidence, "recorded_at")
    check_negative_control(evidence, REQUESTED, DIAGNOSTIC)

    target_char = os.path.join(cfg["target_dir"], SLOT)
    check_file_hash(os.path.join(cfg["target_dir"], "manifest.json"), evidence.get("target_manifest_sha256"), "Target manifest hash")
    check_file_hash(target_char, evidence.get("target_character_sha256"), "Target character file hash")
    check_file_hash(os.path.join(cfg["fixture_dir"], "fixture_manifest.json"), evidence.get("fixture_manifest_sha256"), "Fixture manifest hash")
    expect_field(evidence, "fixture_script", "fixture.rb", "Evidence fixture_script")
    check_file_hash(os.path.join(cfg["fixture_dir"], "fixture.rb"), evidence.get("fixture_script_sha256"), "Fixture script hash")
    for kind, rtp in (("positive", ["generated/rmvx"]), ("negative", [])):
        conf = evidence.get(f"{kind}_runtime_configuration")
        mkxp.check_portable_config(conf, 2, FIXTURE_REL, rtp, f"{kind.capitalize()} runtime configuration")
        require(config_sha256(conf, indent=2) == evidence.get(f"{kind}_runtime_configuration_sha256"),
                f"{kind.capitalize()} runtime configuration hash mismatch")

    check_log(cfg["artifacts_dir"], evidence, "positive",
              required_text=["SUPERRTP_RGSS2_SCREEN 544x416", "SUPERRTP_RMVX_CHARACTER_LOADED 288x256", "SUPERRTP_RMVX_RENDER_DONE"])
    check_log(cfg["artifacts_dir"], evidence, "negative", required_text=[DIAGNOSTIC])

    results = {}

    def inspect(name, path):
        mode = "negative_control" if "negative" in name else "positive"
        results[f"{mode}" if mode == "negative_control" else "positive_control"] = verify_vx_family_screenshot(path, target_char_path=target_char, mode=mode)
        return "Visual content: VERIFIED"

    check_screenshots(cfg["artifacts_dir"], evidence.get("screenshots", {}), inspect)
    require(evidence.get("visual_verification") == results, "visual_verification does not match the re-inspected screenshots")
    print("ALL RPG MAKER VX CHARACTER RUNTIME EVIDENCE CHECKS PASSED: Evidence chain is durable and verified.")
    return True


def main():
    parser = argparse.ArgumentParser(description="SuperRTP RPG Maker VX character runtime verifier (mkxp-z)")
    parser.add_argument("--verify", action="store_true", help="Verify committed evidence (default action)")
    parser.add_argument("--run-capture", action="store_true", help="Re-capture with live mkxp-z first")
    parser.add_argument("--evidence-file", default=None, help="Evidence file to verify")
    parser.add_argument("--artifacts-dir", default=None, help="Use DIR instead of artifacts/runtime/rmvx/character")
    args = parser.parse_args()
    cfg = get_target_config(os.path.abspath(args.artifacts_dir) if args.artifacts_dir else None)
    if args.run_capture:
        run_capture(cfg)
    verify_evidence_chain(args.evidence_file, cfg)


if __name__ == "__main__":
    main()
