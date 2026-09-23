#!/usr/bin/env python3
"""
RPG Maker VX Ace (RGSS3) character runtime verification through mkxp-z.

VX Ace shares the VX standard 8-character sheet layout, so the Actor1.png bytes of the
rmvx and rmvxace packs must be identical while the targets keep separate identities,
transform policies and runtime proofs. The capture and pixel checks are shared with
tools/verify_rmvx_runtime.py; this module owns the RGSS3-specific evidence contract:
the mkxp-z startup banner, full build metadata, and the cross-target byte equality.

Usage:
  python3 tools/verify_rmvxace_runtime.py --verify
  python3 tools/verify_rmvxace_runtime.py --run-capture
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mkxp_runtime as mkxp
from evidence import (check_file_hash, check_timestamp, config_sha256, expect_field, load_evidence, read_text, require,
                      write_evidence)
from registry import load_slot_mapping
from repo import evidence_timestamp, repo_path, sha256_file
from verify_rmvx_runtime import SLOT, capture_vx_family, verify_vx_family_screenshot

PINNED_MKXP_COMMIT = mkxp.PINNED_MKXP_COMMIT
CANONICAL_ASSET_ID = "test.calibration.walking-character"
CANONICAL_SOURCE = repo_path("registry", "assets", "test_calibration_walking_character.rgba")
REQUESTED = "Graphics/Characters/Actor1"
FIXTURE_REL = "tests/fixtures/rmvxace_character_min"
STARTUP_BANNER = "RGSS version 3 (RPG Maker VX Ace) "  # trailing space is part of mkxp-z's log line
POSITIVE_MARKERS = ("SUPERRTP_RGSS3_SCREEN 544x416", "SUPERRTP_RMVXACE_CHARACTER_LOADED 288x256", "SUPERRTP_RMVXACE_RENDER_DONE")


def get_target_config(artifacts_dir=None):
    artifacts_dir = artifacts_dir or repo_path("artifacts", "runtime", "rmvxace", "character")
    return {
        "target": "rmvxace",
        "engine": "RPG Maker VX Ace",
        "engine_mode": "rgss3",
        "rgss_version": 3,
        "category": "Character",
        "expected_character_slot": "Actor1",
        "transform_policy": load_slot_mapping("rmvxace")["slots"][SLOT]["transform_policy"],
        "fixture_dir": repo_path(FIXTURE_REL),
        "target_dir": repo_path("generated", "rmvxace"),
        "rmvx_target_dir": repo_path("generated", "rmvx"),
        "artifacts_dir": artifacts_dir,
        "evidence_path": os.path.join(artifacts_dir, "verification_evidence.json"),
    }


def run_capture(cfg=None):
    """Live RMVX Ace capture; writes <artifacts_dir>/verification_evidence.json."""
    cfg = cfg or get_target_config()
    cap = capture_vx_family("rmvxace", 3, FIXTURE_REL, "RMVXACE", cfg["artifacts_dir"])
    if STARTUP_BANNER.strip() not in cap.pos.log:
        raise ValueError(f"Positive log missing expected RGSS3 startup banner: '{STARTUP_BANNER.strip()}'")
    match = re.search(r"SUPERRTP_RMVXACE_MISSING_ASSET:\s*(.+)", cap.neg.log)
    if not match or REQUESTED not in match.group(1):
        raise ValueError("Negative log missing SUPERRTP_RMVXACE_MISSING_ASSET diagnostic for Graphics/Characters/Actor1")

    rmvx_char = os.path.join(cfg["rmvx_target_dir"], SLOT)
    if not os.path.exists(rmvx_char):
        raise FileNotFoundError(f"Reference RMVX character file not found at {rmvx_char}; build the rmvx target first")
    ace_sha, vx_sha = sha256_file(cap.target_char), sha256_file(rmvx_char)
    if ace_sha != vx_sha:
        raise ValueError("Actor1.png bytes in rmvxace do not match rmvx Actor1.png bytes")

    evidence = {
        "target": "rmvxace",
        "engine": cfg["engine"],
        "engine_mode": cfg["engine_mode"],
        "rgss_version": 3,
        "runtime": "mkxp-z",
        "runtime_commit": PINNED_MKXP_COMMIT,
        "startup_log_identity": STARTUP_BANNER,
        "category": cfg["category"],
        "requested_resource": REQUESTED,
        "canonical_asset_id": CANONICAL_ASSET_ID,
        "canonical_asset_sha256": sha256_file(CANONICAL_SOURCE),
        "source_character_indices": list(range(8)),
        "transform_policy": cfg["transform_policy"],
        "target_manifest_sha256": sha256_file(os.path.join(cap.target_dir, "manifest.json")),
        "actor1_png_sha256": ace_sha,
        "rmvx_actor1_reference_sha256": vx_sha,
        "rmvx_byte_equality": "IDENTICAL",
        "fixture_script_sha256": sha256_file(os.path.join(cfg["fixture_dir"], "fixture.rb")),
        "fixture_manifest_sha256": sha256_file(os.path.join(cfg["fixture_dir"], "fixture_manifest.json")),
        "positive_portable_config": cap.pos_conf,
        "positive_portable_config_sha256": config_sha256(cap.pos_conf),
        "negative_portable_config": cap.neg_conf,
        "negative_portable_config_sha256": config_sha256(cap.neg_conf),
        "positive_exit_code": cap.pos.exit_code,
        "negative_exit_code": cap.neg.exit_code,
        "positive_runtime_log_sha256": sha256_file(cap.logs["positive"]),
        "negative_runtime_log_sha256": sha256_file(cap.logs["negative"]),
        "negative_diagnostic": match.group(1).strip(),
        "positive_screenshot_sha256": sha256_file(cap.pos_path),
        "negative_screenshot_sha256": sha256_file(cap.neg_path),
        "positive_visual_verification": cap.pos_vis,
        "negative_visual_verification": cap.neg_vis,
        "build_metadata": cap.build_meta,
        "timestamp": evidence_timestamp(),
    }
    write_evidence(cfg["evidence_path"], evidence)
    return evidence


def verify_evidence_chain(evidence_path=None, artifacts_dir=None):
    """Verifies RMVX Ace evidence against the current files and re-inspects screenshots."""
    cfg = get_target_config(artifacts_dir)
    ev = load_evidence(evidence_path or cfg["evidence_path"])
    artifacts_dir = cfg["artifacts_dir"]

    for field, expected in (("target", "rmvxace"), ("engine", cfg["engine"]), ("engine_mode", "rgss3"), ("rgss_version", 3),
                            ("runtime", "mkxp-z"), ("runtime_commit", PINNED_MKXP_COMMIT),
                            ("startup_log_identity", STARTUP_BANNER), ("category", "Character"),
                            ("requested_resource", REQUESTED), ("canonical_asset_id", CANONICAL_ASSET_ID),
                            ("source_character_indices", list(range(8))), ("transform_policy", cfg["transform_policy"]),
                            ("rmvx_byte_equality", "IDENTICAL"), ("positive_exit_code", 0), ("negative_exit_code", 1)):
        expect_field(ev, field, expected)
    mkxp.check_build_metadata(ev.get("build_metadata"), where="evidence build_metadata")
    check_timestamp(ev, "timestamp")

    check_file_hash(CANONICAL_SOURCE, ev.get("canonical_asset_sha256"), "Canonical source asset hash")
    check_file_hash(os.path.join(cfg["target_dir"], "manifest.json"), ev.get("target_manifest_sha256"), "Target manifest hash")
    target_char = os.path.join(cfg["target_dir"], SLOT)
    check_file_hash(target_char, ev.get("actor1_png_sha256"), "Actor1.png hash")
    check_file_hash(os.path.join(cfg["rmvx_target_dir"], SLOT), ev.get("rmvx_actor1_reference_sha256"), "Reference RMVX Actor1.png hash")
    require(ev.get("actor1_png_sha256") == ev.get("rmvx_actor1_reference_sha256"), "Actor1 SHA does not equal RMVX reference SHA in evidence")
    check_file_hash(os.path.join(cfg["fixture_dir"], "fixture.rb"), ev.get("fixture_script_sha256"), "Fixture script hash")
    check_file_hash(os.path.join(cfg["fixture_dir"], "fixture_manifest.json"), ev.get("fixture_manifest_sha256"), "Fixture manifest hash")

    for kind, rtp in (("positive", ["generated/rmvxace"]), ("negative", [])):
        conf = ev.get(f"{kind}_portable_config")
        mkxp.check_portable_config(conf, 3, FIXTURE_REL, rtp, f"{kind.capitalize()} config")
        require(config_sha256(conf) == ev.get(f"{kind}_portable_config_sha256"), f"{kind.capitalize()} portable config hash mismatch")

    pos_log = os.path.join(artifacts_dir, "positive_runtime.log")
    check_file_hash(pos_log, ev.get("positive_runtime_log_sha256"), "Positive runtime log hash")
    pos_text = read_text(pos_log)
    for marker in (STARTUP_BANNER.strip(),) + POSITIVE_MARKERS:
        require(marker in pos_text, f"Required positive runtime log marker not found in {pos_log}: '{marker}'")
    neg_log = os.path.join(artifacts_dir, "negative_runtime.log")
    check_file_hash(neg_log, ev.get("negative_runtime_log_sha256"), "Negative runtime log hash")
    require(bool(ev.get("negative_diagnostic")) and ev["negative_diagnostic"] in read_text(neg_log), "Negative diagnostic not found in negative runtime log")
    require(REQUESTED in ev["negative_diagnostic"], "Negative diagnostic does not mention Graphics/Characters/Actor1")

    pos_shot = os.path.join(artifacts_dir, "rmvxace_character_positive.png")
    neg_shot = os.path.join(artifacts_dir, "rmvxace_character_negative_control.png")
    check_file_hash(pos_shot, ev.get("positive_screenshot_sha256"), "Positive screenshot hash")
    check_file_hash(neg_shot, ev.get("negative_screenshot_sha256"), "Negative screenshot hash")
    require(ev.get("positive_visual_verification") == verify_vx_family_screenshot(pos_shot, target_char_path=target_char, mode="positive"),
            "positive_visual_verification does not match the re-inspected screenshot")
    require(ev.get("negative_visual_verification") == verify_vx_family_screenshot(neg_shot, mode="negative_control"),
            "negative_visual_verification does not match the re-inspected screenshot")

    print("ALL RUNTIME EVIDENCE CHECKS PASSED: Evidence chain is durable and verified.")
    return 0


def main():
    parser = argparse.ArgumentParser(description="SuperRTP RPG Maker VX Ace character runtime verifier (mkxp-z)")
    parser.add_argument("--verify", action="store_true", help="Verify committed evidence (default action)")
    parser.add_argument("--run-capture", action="store_true", help="Re-capture with live mkxp-z first")
    parser.add_argument("--evidence-file", default=None, help="Evidence file to verify")
    parser.add_argument("--artifacts-dir", default=None, help="Use DIR instead of artifacts/runtime/rmvxace/character")
    args = parser.parse_args()
    artifacts_dir = os.path.abspath(args.artifacts_dir) if args.artifacts_dir else None
    if args.run_capture:
        run_capture(get_target_config(artifacts_dir))
    verify_evidence_chain(args.evidence_file, artifacts_dir)


if __name__ == "__main__":
    main()
