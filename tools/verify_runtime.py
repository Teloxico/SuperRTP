#!/usr/bin/env python3
"""
RPG Maker 2000/2003 CharSet runtime verification through EasyRPG Player.

Positive control: the fixture (tests/fixtures/<target>_min) bundles no CharSet, so the
hero sprite must resolve from the generated SuperRTP pack via the RTP alias the fixture
requests (Actor1 for rm2000, Hero1 for rm2003). Key presses turn the hero through all
four directions; each facing is captured once shown and its arrow shape and screen
position are checked.

Negative control: the same fixture with the RTP disabled must log
"Image not found: CharSet/<name>" and show EasyRPG's missing-image placeholder.

Evidence lives in artifacts/runtime/<target>/charset/verification_evidence.json.

Usage:
  python3 tools/verify_runtime.py --target all --verify       # check committed evidence
  python3 tools/verify_runtime.py --target all --run-capture  # re-capture, then verify
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import easyrpg_runtime as easyrpg
from build_target import build_target
from evidence import (check_file_hash, check_log, check_negative_control, check_screenshots, check_timestamp,
                      expect_field, load_evidence, read_text, require, write_evidence)
from png_utils import decode_png_rgb
from runtime_harness import press_key
from repo import evidence_timestamp, repo_path, sha256_file

CANONICAL_ASSET_ID = "test.calibration.walking-character"
CANONICAL_SOURCE = repo_path("registry", "assets", "test_calibration_walking_character.rgba")

# The fixture requests a different RTP name per engine to exercise the alias tables.
REQUESTED_CHARSET = {"rm2000": "Actor1", "rm2003": "Hero1"}

# The hero starts facing down; each key press turns it, and each facing is captured once
# the screen shows it (see tools/easyrpg_runtime.py for why --replay-input is not used).
DIRECTIONS = ("down", "left", "up", "right")
TURN_KEYS = ("Left", "Up", "Right")

# Expected screen-space centroid of the hero's cyan body per facing (640x480, 2x scale).
EXPECTED_CENTROIDS = {
    "down": {"x": (320, 345), "y": (210, 230)},
    "left": {"x": (295, 315), "y": (215, 230)},
    "up": {"x": (295, 315), "y": (180, 200)},
    "right": {"x": (325, 345), "y": (180, 200)},
}


def get_target_config(target="rm2000", artifacts_dir=None):
    fixture_dir = repo_path("tests", "fixtures", f"{target}_min")
    artifacts_dir = artifacts_dir or repo_path("artifacts", "runtime", target, "charset")
    return {
        "target": target,
        "engine": easyrpg.ENGINE_MODES[target],
        "artifacts_dir": artifacts_dir,
        "evidence_path": os.path.join(artifacts_dir, "verification_evidence.json"),
        "fixture_dir": fixture_dir,
        "target_dir": repo_path("generated", target),
    }


# ---------------------------------------------------------------------------
# Pixel inspection
# ---------------------------------------------------------------------------

# Grass color of the fixture ChipSet (tools/generate_fixture_graphics.py); its presence
# proves the map screen is shown rather than EasyRPG's start-up splash.
FIXTURE_GRASS = (46, 139, 87)


def _verify_negative_screenshot(pixels):
    """Map shown, EasyRPG's missing-image warning banner, and the placeholder where the hero would be."""
    text_pixels = easyrpg.require_warning_banner(pixels)
    grass = sum(row.count(FIXTURE_GRASS) for row in pixels[300:480])
    if grass < 50000:
        raise ValueError(f"Negative control does not show the fixture map: {grass} grass pixels in the lower screen")
    center_colors = {pixels[y][x] for y in range(180, 260) for x in range(300, 340)} - {FIXTURE_GRASS}
    if len(center_colors) < 2:
        raise ValueError("Negative control missing missing-asset placeholder in center")
    return {"status": "VERIFIED", "error_text_pixels": text_pixels}


def verify_directional_screenshot(filepath, expected_direction, target=None):
    """
    Checks one captured frame: the hero's screen position for the facing, and the arrow
    shape (tip versus wings), which catches row-order inversions.
    `expected_direction` is 'down', 'left', 'up', 'right' or 'negative_control'.
    """
    target = target or ("rm2003" if "rm2003" in filepath else "rm2000")
    w, h, pixels = decode_png_rgb(filepath)
    if (w, h) != (easyrpg.SCREEN_W, easyrpg.SCREEN_H):
        raise ValueError(f"Unexpected image dimensions {w}x{h} in {filepath}, expected 640x480")
    if expected_direction == "negative_control":
        return _verify_negative_screenshot(pixels)

    region = [(x, y) for y in range(160, 260) for x in range(270, 370)]
    cyans = [(x, y) for x, y in region if pixels[y][x][0] < 50 and pixels[y][x][1] > 180 and pixels[y][x][2] > 180]
    accents = [(x, y) for x, y in region if pixels[y][x][0] > 200 and pixels[y][x][1] > 180 and pixels[y][x][2] < 100]
    if len(cyans) < 30 or len(accents) < 10:
        raise ValueError(f"Character sprite not found in expected center region for {filepath} (cyans={len(cyans)}, yellows={len(accents)})")

    c_x = sum(x for x, _ in cyans) / len(cyans)
    c_y = sum(y for _, y in cyans) / len(cyans)
    exp = EXPECTED_CENTROIDS[expected_direction]
    if not (exp["x"][0] <= c_x <= exp["x"][1] and exp["y"][0] <= c_y <= exp["y"][1]):
        raise ValueError(f"Direction position mismatch for '{expected_direction}' ({target}): center is ({c_x:.1f}, {c_y:.1f}), "
                         f"expected x in {exp['x']}, y in {exp['y']}")

    min_x, max_x = min(x for x, _ in cyans), max(x for x, _ in cyans)
    min_y, max_y = min(y for _, y in cyans), max(y for _, y in cyans)

    def span(values):
        return max(values) - min(values) + 1

    top_w = span([x for x, y in cyans if y <= min_y + 4])
    bot_w = span([x for x, y in cyans if y >= max_y - 4])
    left_h = span([y for x, y in cyans if x <= min_x + 4])
    right_h = span([y for x, y in cyans if x >= max_x - 4])

    # A down arrow has its wide wings at the top; an up arrow at the bottom; and so on.
    if expected_direction in ("down", "up"):
        wide_top = top_w > bot_w
        if wide_top != (expected_direction == "down") or top_w == bot_w:
            relation = "top_w > bot_w" if expected_direction == "down" else "top_w < bot_w"
            raise ValueError(f"Sprite arrow shape mismatch: expected {expected_direction.upper()} ({relation}), got top_w={top_w}, bot_w={bot_w}")
        if abs(left_h - right_h) > 6:
            raise ValueError(f"Sprite arrow shape asymmetry for {expected_direction.upper()}: left_h={left_h}, right_h={right_h}")
    elif expected_direction == "left" and left_h >= right_h:
        raise ValueError(f"Sprite arrow shape mismatch: expected LEFT (left_h < right_h), got left_h={left_h}, right_h={right_h}")
    elif expected_direction == "right" and right_h >= left_h:
        raise ValueError(f"Sprite arrow shape mismatch: expected RIGHT (right_h < left_h), got left_h={left_h}, right_h={right_h}")

    return {
        "status": "VERIFIED",
        "facing": expected_direction.upper(),
        "centroid": [round(c_x, 1), round(c_y, 1)],
        "shape_metrics": {"top_w": top_w, "bot_w": bot_w, "left_h": left_h, "right_h": right_h},
        "cyan_pixel_count": len(cyans),
        "accent_pixel_count": len(accents),
    }


def _direction_of(shot_name: str) -> str:
    if "negative_control" in shot_name:
        return "negative_control"
    for direction in DIRECTIONS:
        if f"_{direction}." in shot_name:
            return direction
    raise ValueError(f"Cannot infer direction from screenshot name '{shot_name}'")


# ---------------------------------------------------------------------------
# Evidence verification
# ---------------------------------------------------------------------------

def verify_evidence_chain(target="rm2000", evidence_path=None, artifacts_dir=None):
    """Verifies evidence against the current files and re-inspects every screenshot."""
    cfg = get_target_config(target, artifacts_dir)
    evidence = load_evidence(evidence_path or cfg["evidence_path"])
    charset = REQUESTED_CHARSET[target]
    print(f"=== SuperRTP Runtime Verification Evidence Check ({target}) ===")
    print(f"Requested Slot:  {evidence.get('requested_charset')}   EasyRPG: {evidence.get('easyrpg_version')}   Recorded: {evidence.get('recorded_at')}")

    expect_field(evidence, "target", target, "Evidence target")
    expect_field(evidence, "engine_mode", cfg["engine"], "Evidence engine_mode")
    expect_field(evidence, "requested_charset", charset, "Evidence requested_charset")
    require(evidence.get("canonical_asset_id") == CANONICAL_ASSET_ID, f"Unexpected canonical_asset_id: {evidence.get('canonical_asset_id')}")
    check_file_hash(CANONICAL_SOURCE, evidence.get("canonical_source_sha256"), "Canonical source SHA-256")
    easyrpg.check_pinned_version(evidence.get("easyrpg_version", ""))
    check_timestamp(evidence, "recorded_at")

    check_file_hash(os.path.join(cfg["target_dir"], "manifest.json"), evidence.get("target_manifest_sha256"), "Target manifest hash")
    check_file_hash(os.path.join(cfg["target_dir"], "CharSet", "Actor1.png"), evidence.get("target_actor1_sha256"), "Target Actor1.png hash")
    check_file_hash(os.path.join(cfg["fixture_dir"], "fixture_manifest.json"), evidence.get("fixture_manifest_sha256"), "Fixture manifest hash")
    expect_field(evidence, "input_keys", list(TURN_KEYS), "Evidence input_keys")

    diagnostic = f"Image not found: CharSet/{charset}"
    check_log(cfg["artifacts_dir"], evidence, "positive")
    check_log(cfg["artifacts_dir"], evidence, "negative", required_text=[diagnostic])
    check_negative_control(evidence, f"CharSet/{charset}", diagnostic)

    results = {}

    def inspect(name, path):
        results[_direction_of(name)] = verify_directional_screenshot(path, _direction_of(name), target)
        return "Visual content: " + results[_direction_of(name)]["status"]

    check_screenshots(cfg["artifacts_dir"], evidence.get("screenshots", {}), inspect)
    require(evidence.get("directional_evidence") == results, "directional_evidence does not match the re-inspected screenshots")
    print(f"ALL RUNTIME EVIDENCE CHECKS PASSED ({target}): Evidence chain is durable and verified.")
    return True


# ---------------------------------------------------------------------------
# Live capture
# ---------------------------------------------------------------------------

def run_capture_and_record(target="rm2000", artifacts_dir=None):
    """Runs the live positive and negative sessions, inspects the frames and writes evidence."""
    cfg = get_target_config(target, artifacts_dir)
    player = easyrpg.find_player()
    version = easyrpg.player_version(player)
    easyrpg.check_pinned_version(version)
    build_target(target, output_dir=cfg["target_dir"], clean=True)
    os.makedirs(cfg["artifacts_dir"], exist_ok=True)

    charset = REQUESTED_CHARSET[target]
    pos_log = os.path.join(cfg["artifacts_dir"], "positive_runtime.log")
    neg_log = os.path.join(cfg["artifacts_dir"], "negative_runtime.log")
    shot_paths = {d: os.path.join(cfg["artifacts_dir"], f"{target}_charset_{d}.png") for d in DIRECTIONS}

    print(f"Executing EasyRPG positive control for {target} under Xvfb (turning the hero with key presses)...")
    command = easyrpg.player_command(player, cfg["fixture_dir"], cfg["engine"], rtp_dir=cfg["target_dir"], log_file=pos_log)
    with easyrpg.session(command, log_file=pos_log) as display:
        for key, direction in zip((None,) + TURN_KEYS, DIRECTIONS):
            if key:
                press_key(display, key)
            easyrpg.wait_for(display, lambda png, d=direction: bool(verify_directional_screenshot(png, d, target)),
                             shot_paths[direction], timeout=30 if key is None else 10)

    screenshots, directional = {}, {}
    for direction in DIRECTIONS:
        path = shot_paths[direction]
        directional[direction] = verify_directional_screenshot(path, direction, target)
        screenshots[os.path.basename(path)] = sha256_file(path)
        print(f"Captured {os.path.basename(path)} ({directional[direction]['status']})")

    print(f"Executing EasyRPG negative control for {target} under Xvfb...")
    neg_name = f"{target}_charset_negative_control.png"
    neg_path = os.path.join(cfg["artifacts_dir"], neg_name)
    with easyrpg.session(easyrpg.player_command(player, cfg["fixture_dir"], cfg["engine"], log_file=neg_log), log_file=neg_log) as display:
        easyrpg.wait_for(display, lambda png: bool(verify_directional_screenshot(png, "negative_control", target)), neg_path)
    neg_result = verify_directional_screenshot(neg_path, "negative_control", target)
    directional["negative_control"] = neg_result
    screenshots[neg_name] = sha256_file(neg_path)

    match = re.search(r"Image not found: ([^\r\n]+)", read_text(neg_log))
    if not match:
        raise ValueError(f"Could not extract 'Image not found' diagnostic from negative control log: {neg_log}")
    diagnostic = f"Image not found: {match.group(1).strip()}"

    evidence = {
        "target": target,
        "engine_mode": cfg["engine"],
        "requested_charset": charset,
        "canonical_asset_id": CANONICAL_ASSET_ID,
        "canonical_source_sha256": sha256_file(CANONICAL_SOURCE),
        "target_manifest_sha256": sha256_file(os.path.join(cfg["target_dir"], "manifest.json")),
        "target_actor1_sha256": sha256_file(os.path.join(cfg["target_dir"], "CharSet", "Actor1.png")),
        "fixture_manifest_sha256": sha256_file(os.path.join(cfg["fixture_dir"], "fixture_manifest.json")),
        "input_keys": list(TURN_KEYS),
        "positive_runtime_log": "positive_runtime.log",
        "positive_runtime_log_sha256": sha256_file(pos_log),
        "negative_runtime_log": "negative_runtime.log",
        "negative_runtime_log_sha256": sha256_file(neg_log),
        "easyrpg_version": version,
        "recorded_at": evidence_timestamp(),
        "negative_control": {
            "status": neg_result["status"],
            "expected_missing_asset": f"CharSet/{charset}",
            "diagnostic": diagnostic,
            "screenshot": neg_name,
            "screenshot_sha256": screenshots[neg_name],
        },
        "screenshots": screenshots,
        "directional_evidence": directional,
    }
    write_evidence(cfg["evidence_path"], evidence)
    return evidence


def main():
    parser = argparse.ArgumentParser(description="SuperRTP RM2000/RM2003 CharSet runtime verifier (EasyRPG Player)")
    parser.add_argument("--target", default="rm2000", choices=["rm2000", "rm2003", "all"])
    parser.add_argument("--verify", action="store_true", help="Verify committed evidence (default action)")
    parser.add_argument("--run-capture", action="store_true", help="Re-capture with live EasyRPG Player first")
    parser.add_argument("--artifacts-dir", default=None, help="Use DIR/<target> instead of artifacts/runtime/<target>/charset")
    args = parser.parse_args()

    targets = ["rm2000", "rm2003"] if args.target == "all" else [args.target]
    for t in targets:
        artifacts_dir = os.path.join(os.path.abspath(args.artifacts_dir), t) if args.artifacts_dir else None
        if args.run_capture:
            run_capture_and_record(t, artifacts_dir)
        verify_evidence_chain(t, artifacts_dir=artifacts_dir)


if __name__ == "__main__":
    main()
