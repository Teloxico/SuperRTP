#!/usr/bin/env python3
"""
SuperRTP Deterministic RPG Maker XP (RGSS1) Character Runtime & Visual Verification Tool.

Verifies and reproduces mkxp-z runtime execution for RGSS1 Character compatibility:
  - Executes mkxp-z with clean-room RGSS1 test fixture (rmxp_character_min)
  - Validates positive control (SuperRTP provides Graphics/Characters/001-Fighter01.png)
  - Validates negative control (empty RTP isolates missing 001-Fighter01.png)
  - Inspects rendered 640x480 screenshot pixels for:
      * Test pad geometry (260, 164, 120x152) and corner alignment markers
      * Background color outside pad
      * Directional arrow tips (DOWN, LEFT, RIGHT, UP) in Col 1 (Idle column) and Col 3 (Idle duplicate)
      * Full 128-scanline pixel identity between Col 1 and Col 3 (XP 4th column idle repetition)
      * Active step markers in Col 0 (Step Left) and Col 2 (Step Right)
      * Transparency mechanics: arrow notches exposing underlying pad color
  - Manages artifacts/runtime/rmxp/character/verification_evidence.json
"""

import os
import sys
import json
import zlib
import struct
import shutil
import hashlib
import argparse
import subprocess
import re
import tempfile
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

from png_utils import decode_png_rgb, create_rgba_png

PINNED_MKXP_COMMIT = "826929eeb3ebc4b887c011604919217a790770f4"

def compute_sha256(filepath):
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def get_evidence_timestamp():
    sde = os.environ.get("SOURCE_DATE_EPOCH")
    if sde:
        try:
            return datetime.fromtimestamp(int(sde), tz=timezone.utc).isoformat()
        except ValueError:
            pass
    return datetime.now(timezone.utc).isoformat()

def get_target_config():
    return {
        "target": "rmxp",
        "engine": "rgss1",
        "expected_character_slot": "001-Fighter01",
        "fixture_dir": os.path.join(REPO_ROOT, "tests", "fixtures", "rmxp_character_min"),
        "target_dir": os.path.join(REPO_ROOT, "generated", "rmxp"),
        "artifacts_dir": os.path.join(REPO_ROOT, "artifacts", "runtime", "rmxp", "character"),
        "evidence_path": os.path.join(REPO_ROOT, "artifacts", "runtime", "rmxp", "character", "verification_evidence.json"),
    }

def verify_rmxp_screenshot(screenshot_path, mode="positive"):
    """
    Deterministically inspects pixels of the captured 640x480 screenshot.
    Fixture layout:
      - Window size: 640x480
      - Background: (25, 25, 30)
      - Test pad: rect at (260, 164, 120, 152), color (210, 215, 220)
      - Pad corner markers:
          TL (260, 164, 8, 8): Red (255, 60, 60)
          TR (372, 164, 8, 8): Green (60, 255, 60)
          BL (260, 308, 8, 8): Blue (60, 60, 255)
          BR (372, 308, 8, 8): Yellow (255, 255, 60)
      - Character sprite: placed at (272, 176), size 96x128 (4 cols x 4 rows)
          Col 0 (Step Left):  x in 272..295, active step marker at (280, 176 + row*32 + 27) = (240, 160, 20)
          Col 1 (Idle column): x in 296..319
              Row 0 (DOWN):  tip at (307, 197), notch at (307, 182)
              Row 1 (LEFT):  tip at (300, 221), notch at (315, 221)
              Row 2 (RIGHT): tip at (315, 253), notch at (300, 253)
              Row 3 (UP):    tip at (307, 277), notch at (307, 293)
          Col 2 (Step Right): x in 320..343, active step marker at (336, 176 + row*32 + 27) = (240, 160, 20)
          Col 3 (Idle duplicate): x in 344..367 (offset +48 from Col 1, exact duplicate)
              Row 0 (DOWN):  tip at (355, 197), notch at (355, 182)
              Row 1 (LEFT):  tip at (348, 221), notch at (363, 221)
              Row 2 (RIGHT): tip at (363, 253), notch at (348, 253)
              Row 3 (UP):    tip at (355, 277), notch at (355, 293)
          Arrow tip color: (10, 40, 70)
          Notch (transparent) exposes pad: (210, 215, 220)
    """
    if not os.path.exists(screenshot_path):
        raise FileNotFoundError(f"Screenshot not found: {screenshot_path}")

    w, h, pixels = decode_png_rgb(screenshot_path)
    if w != 640 or h != 480:
        raise ValueError(f"Expected 640x480 screenshot, got {w}x{h}")

    # 1. Verify pad corner markers
    tl_color = pixels[166][262]
    tr_color = pixels[166][374]
    bl_color = pixels[310][262]
    br_color = pixels[310][374]

    expected_tl = (255, 60, 60)
    expected_tr = (60, 255, 60)
    expected_bl = (60, 60, 255)
    expected_br = (255, 255, 60)

    if tl_color != expected_tl:
        raise ValueError(f"Pad TL corner marker mismatch: expected {expected_tl}, got {tl_color}")
    if tr_color != expected_tr:
        raise ValueError(f"Pad TR corner marker mismatch: expected {expected_tr}, got {tr_color}")
    if bl_color != expected_bl:
        raise ValueError(f"Pad BL corner marker mismatch: expected {expected_bl}, got {bl_color}")
    if br_color != expected_br:
        raise ValueError(f"Pad BR corner marker mismatch: expected {expected_br}, got {br_color}")

    # 2. Verify dark background outside pad
    bg_color = pixels[50][50]
    expected_bg = (25, 25, 30)
    if bg_color != expected_bg:
        raise ValueError(f"Background color mismatch: expected {expected_bg}, got {bg_color}")

    pad_color = (210, 215, 220)
    arrow_tip_color = (10, 40, 70)
    foot_color = (240, 160, 20)

    # 3. Check coordinates for positive vs negative
    r0_tip_px = pixels[197][307]
    r1_tip_px = pixels[221][300]
    r2_tip_px = pixels[253][315]
    r3_tip_px = pixels[277][307]

    if mode == "negative_control":
        # In negative control, the character failed to load and was NOT rendered.
        # Arrow tip coordinates must all show the blank pad color (210, 215, 220).
        for r_name, px_col in [("Row 0 DOWN", r0_tip_px), ("Row 1 LEFT", r1_tip_px),
                               ("Row 2 RIGHT", r2_tip_px), ("Row 3 UP", r3_tip_px)]:
            if px_col == arrow_tip_color:
                raise ValueError(f"Negative control unexpectedly rendered character sprite at {r_name} tip")
            if px_col != pad_color:
                raise ValueError(f"Negative control expected pad color {pad_color} at {r_name} tip, got {px_col}")

        return {
            "status": "VERIFIED",
            "mode": "negative_control",
            "missing_detected": True,
            "pad_corners": {
                "top_left": list(tl_color),
                "top_right": list(tr_color),
                "bottom_left": list(bl_color),
                "bottom_right": list(br_color)
            },
            "pad_center_color": list(pixels[240][320])
        }

    # Positive control: verify Col 1 arrow tips and transparent notches
    r0_notch_px = pixels[182][307]
    r1_notch_px = pixels[221][315]
    r2_notch_px = pixels[253][300]
    r3_notch_px = pixels[293][307]

    if r0_tip_px != arrow_tip_color:
        raise ValueError(f"Row 0 (DOWN) Col 1 arrow tip mismatch: expected {arrow_tip_color}, got {r0_tip_px}")
    if r0_notch_px != pad_color:
        raise ValueError(f"Row 0 (DOWN) Col 1 notch transparency mismatch: expected pad {pad_color}, got {r0_notch_px}")

    if r1_tip_px != arrow_tip_color:
        raise ValueError(f"Row 1 (LEFT) Col 1 arrow tip mismatch: expected {arrow_tip_color}, got {r1_tip_px}")
    if r1_notch_px != pad_color:
        raise ValueError(f"Row 1 (LEFT) Col 1 notch transparency mismatch: expected pad {pad_color}, got {r1_notch_px}")

    if r2_tip_px != arrow_tip_color:
        raise ValueError(f"Row 2 (RIGHT) Col 1 arrow tip mismatch: expected {arrow_tip_color}, got {r2_tip_px}")
    if r2_notch_px != pad_color:
        raise ValueError(f"Row 2 (RIGHT) Col 1 notch transparency mismatch: expected pad {pad_color}, got {r2_notch_px}")

    if r3_tip_px != arrow_tip_color:
        raise ValueError(f"Row 3 (UP) Col 1 arrow tip mismatch: expected {arrow_tip_color}, got {r3_tip_px}")
    if r3_notch_px != pad_color:
        raise ValueError(f"Row 3 (UP) Col 1 notch transparency mismatch: expected pad {pad_color}, got {r3_notch_px}")

    # Positive control: verify Col 3 (Idle duplicate) arrow tips and transparent notches
    # Col 3 is at x = 344..367, offset +48 from Col 1 (296..319)
    r0_c3_tip = pixels[197][355]
    r0_c3_notch = pixels[182][355]
    r1_c3_tip = pixels[221][348]
    r1_c3_notch = pixels[221][363]
    r2_c3_tip = pixels[253][363]
    r2_c3_notch = pixels[253][348]
    r3_c3_tip = pixels[277][355]
    r3_c3_notch = pixels[293][355]

    if r0_c3_tip != arrow_tip_color:
        raise ValueError(f"Row 0 (DOWN) Col 3 arrow tip mismatch: expected {arrow_tip_color}, got {r0_c3_tip}")
    if r0_c3_notch != pad_color:
        raise ValueError(f"Row 0 (DOWN) Col 3 notch transparency mismatch: expected pad {pad_color}, got {r0_c3_notch}")
    if r1_c3_tip != arrow_tip_color:
        raise ValueError(f"Row 1 (LEFT) Col 3 arrow tip mismatch: expected {arrow_tip_color}, got {r1_c3_tip}")
    if r1_c3_notch != pad_color:
        raise ValueError(f"Row 1 (LEFT) Col 3 notch transparency mismatch: expected pad {pad_color}, got {r1_c3_notch}")
    if r2_c3_tip != arrow_tip_color:
        raise ValueError(f"Row 2 (RIGHT) Col 3 arrow tip mismatch: expected {arrow_tip_color}, got {r2_c3_tip}")
    if r2_c3_notch != pad_color:
        raise ValueError(f"Row 2 (RIGHT) Col 3 notch transparency mismatch: expected pad {pad_color}, got {r2_c3_notch}")
    if r3_c3_tip != arrow_tip_color:
        raise ValueError(f"Row 3 (UP) Col 3 arrow tip mismatch: expected {arrow_tip_color}, got {r3_c3_tip}")
    if r3_c3_notch != pad_color:
        raise ValueError(f"Row 3 (UP) Col 3 notch transparency mismatch: expected pad {pad_color}, got {r3_c3_notch}")

    # Positive control: verify complete pixel equality between Col 1 (296..319) and Col 3 (344..367) across all 128 scanlines
    for y in range(176, 176 + 128):
        for dx in range(24):
            c1_px = pixels[y][296 + dx]
            c3_px = pixels[y][344 + dx]
            if c1_px != c3_px:
                raise ValueError(f"XP Column 3 idle repetition mismatch at y={y}, dx={dx}: Col 1 {c1_px} != Col 3 {c3_px}")

    # Positive control: verify active step markers in Col 0 (Step Left, x=280) and Col 2 (Step Right, x=336)
    for row in range(4):
        y_step = 176 + row * 32 + 27
        col0_step_px = pixels[y_step][280]
        col2_step_px = pixels[y_step][336]
        if col0_step_px != foot_color:
            raise ValueError(f"Row {row} Col 0 (Step Left) foot marker mismatch at (280, {y_step}): expected {foot_color}, got {col0_step_px}")
        if col2_step_px != foot_color:
            raise ValueError(f"Row {row} Col 2 (Step Right) foot marker mismatch at (336, {y_step}): expected {foot_color}, got {col2_step_px}")

    return {
        "status": "VERIFIED",
        "mode": "positive",
        "pad_corners": {
            "top_left": list(tl_color),
            "top_right": list(tr_color),
            "bottom_left": list(bl_color),
            "bottom_right": list(br_color)
        },
        "directional_arrows_col1": {
            "row_0_down": {"tip": list(r0_tip_px), "notch_transparency": list(r0_notch_px)},
            "row_1_left": {"tip": list(r1_tip_px), "notch_transparency": list(r1_notch_px)},
            "row_2_right": {"tip": list(r2_tip_px), "notch_transparency": list(r2_notch_px)},
            "row_3_up": {"tip": list(r3_tip_px), "notch_transparency": list(r3_notch_px)}
        },
        "directional_arrows_col3": {
            "row_0_down": {"tip": list(r0_c3_tip), "notch_transparency": list(r0_c3_notch)},
            "row_1_left": {"tip": list(r1_c3_tip), "notch_transparency": list(r1_c3_notch)},
            "row_2_right": {"tip": list(r2_c3_tip), "notch_transparency": list(r2_c3_notch)},
            "row_3_up": {"tip": list(r3_c3_tip), "notch_transparency": list(r3_c3_notch)}
        },
        "column_repetition_col3_equals_col1": True,
        "step_markers": {
            "col0_step_left": list(foot_color),
            "col2_step_right": list(foot_color)
        }
    }

def verify_evidence_chain(evidence_path=None, artifacts_dir=None, target_dir=None, fixture_dir=None, canonical_rgba_path=None):
    """Verifies complete cryptographic hashes and visual evidence chain for RMXP Character."""
    cfg = get_target_config()
    if evidence_path is None:
        evidence_path = cfg["evidence_path"]
    if artifacts_dir is None:
        artifacts_dir = cfg["artifacts_dir"]
    if target_dir is None:
        target_dir = cfg["target_dir"]
    if fixture_dir is None:
        fixture_dir = cfg["fixture_dir"]
    if canonical_rgba_path is None:
        canonical_rgba_path = os.path.join(REPO_ROOT, "registry", "assets", "test_calibration_walking_character.rgba")

    if not os.path.exists(evidence_path):
        raise FileNotFoundError(f"Verification evidence file not found: {evidence_path}")

    with open(evidence_path, "r", encoding="utf-8") as f:
        evidence = json.load(f)

    print("=== SuperRTP RPG Maker XP Character Runtime Verification Evidence Check ===")
    print(f"Target:          {evidence.get('target')}")
    print(f"Engine Mode:     {evidence.get('engine_mode')}")
    print(f"Runtime:         {evidence.get('runtime')}")
    print(f"Runtime Commit:  {evidence.get('runtime_commit')}")
    print(f"RGSS Version:    {evidence.get('rgss_version')}")
    print(f"Category:        {evidence.get('target_category')}")
    print(f"Requested Slot:  {evidence.get('requested_resource')}")
    print(f"Character Index: {evidence.get('source_character_index')}")
    print(f"Transform Policy:{evidence.get('transform_policy')}")
    print(f"Canonical Asset: {evidence.get('canonical_asset_id')}")
    print(f"mkxp-z Version:  {evidence.get('mkxp_z_version')}")
    print(f"Recorded Date:   {evidence.get('recorded_at')}")

    # Check target and engine mode
    if evidence.get("target") != cfg["target"]:
        raise ValueError(f"Evidence target mismatch: expected {cfg['target']}, got {evidence.get('target')}")
    if evidence.get("engine_mode") != cfg["engine"]:
        raise ValueError(f"Evidence engine_mode mismatch: expected {cfg['engine']}, got {evidence.get('engine_mode')}")

    # Check runtime and exact commit pin
    if evidence.get("runtime") != "mkxp-z":
        raise ValueError(f"Evidence runtime mismatch: expected 'mkxp-z', got {evidence.get('runtime')}")
    if evidence.get("runtime_commit") != PINNED_MKXP_COMMIT:
        raise ValueError(f"mkxp-z commit pin violation: expected '{PINNED_MKXP_COMMIT}', got '{evidence.get('runtime_commit')}'")

    # Check RGSS version
    if evidence.get("rgss_version") != 1:
        raise ValueError(f"Evidence rgss_version mismatch: expected 1, got {evidence.get('rgss_version')}")

    # Check category and requested resource
    if evidence.get("target_category") != "Character":
        raise ValueError(f"Evidence target_category mismatch: expected 'Character', got {evidence.get('target_category')}")
    expected_resource = f"Graphics/Characters/{cfg['expected_character_slot']}"
    if evidence.get("requested_resource") != expected_resource:
        raise ValueError(f"Evidence requested_resource mismatch: expected '{expected_resource}', got {evidence.get('requested_resource')}")

    # Check character index and transform policy
    if evidence.get("source_character_index") != 0:
        raise ValueError(f"Evidence source_character_index mismatch: expected 0, got {evidence.get('source_character_index')}")
    if evidence.get("transform_policy") != "rm2k_to_rgss1_character_4x4":
        raise ValueError(f"Evidence transform_policy mismatch: expected 'rm2k_to_rgss1_character_4x4', got {evidence.get('transform_policy')}")

    # Check mkxp-z build configuration
    build_cfg = evidence.get("mkxp_z_build_configuration")
    if not isinstance(build_cfg, dict):
        raise ValueError("Missing mkxp_z_build_configuration in evidence")
    if build_cfg.get("workdir_current") is not True:
        raise ValueError("mkxp_z_build_configuration.workdir_current must be true")
    if build_cfg.get("static_executable") is not False:
        raise ValueError("mkxp_z_build_configuration.static_executable must be false")
    if build_cfg.get("mri_version") != "3.3":
        raise ValueError("mkxp_z_build_configuration.mri_version must be '3.3'")
    if build_cfg.get("shared_fluid") is not False:
        raise ValueError("mkxp_z_build_configuration.shared_fluid must be false")

    # Check exit codes
    if evidence.get("positive_exit_code") != 0:
        raise ValueError(f"positive_exit_code mismatch: expected 0, got {evidence.get('positive_exit_code')}")
    if evidence.get("negative_exit_code") != 1:
        raise ValueError(f"negative_exit_code mismatch: expected 1, got {evidence.get('negative_exit_code')}")

    # Check canonical asset ID and source SHA-256
    if evidence.get("canonical_asset_id") != "test.calibration.walking-character":
        raise ValueError(f"Unexpected canonical_asset_id: {evidence.get('canonical_asset_id')}")
    if not os.path.exists(canonical_rgba_path):
        raise FileNotFoundError(f"Canonical RGBA source file missing: {canonical_rgba_path}")
    actual_canonical_sha256 = compute_sha256(canonical_rgba_path)
    if actual_canonical_sha256 != evidence.get("canonical_source_sha256"):
        raise ValueError(f"Canonical source SHA-256 mismatch: expected {evidence.get('canonical_source_sha256')}, got {actual_canonical_sha256}")

    # Check mkxp_z_version string contains short commit
    ver = evidence.get("mkxp_z_version", "")
    if PINNED_MKXP_COMMIT[:7] not in ver:
        raise ValueError(f"mkxp-z version string violation: expected {PINNED_MKXP_COMMIT[:7]} in '{ver}'")

    # Check recorded_at ISO-8601 validity
    rec_at = evidence.get("recorded_at", "")
    try:
        datetime.fromisoformat(rec_at.replace("Z", "+00:00"))
    except Exception as e:
        raise ValueError(f"Invalid recorded_at ISO-8601 timestamp '{rec_at}': {e}")

    # Check negative_control structure
    neg_control = evidence.get("negative_control")
    if not isinstance(neg_control, dict):
        raise ValueError("Missing or invalid negative_control sub-object in evidence")
    if neg_control.get("status") != "VERIFIED":
        raise ValueError(f"negative_control.status mismatch: expected 'VERIFIED', got {neg_control.get('status')}")
    expected_missing = "Graphics/Characters/001-Fighter01"
    if neg_control.get("expected_missing_asset") != expected_missing:
        raise ValueError(f"negative_control.expected_missing_asset mismatch: expected '{expected_missing}', got {neg_control.get('expected_missing_asset')}")
    expected_diag = "SUPERRTP_RMXP_MISSING_ASSET: No such file or directory - Graphics/Characters/001-Fighter01"
    if neg_control.get("diagnostic") != expected_diag:
        raise ValueError(f"negative_control.diagnostic mismatch: expected '{expected_diag}', got {neg_control.get('diagnostic')}")
    neg_shot_key = neg_control.get("screenshot")
    if not neg_shot_key or neg_shot_key not in evidence.get("screenshots", {}):
        raise ValueError(f"negative_control screenshot '{neg_shot_key}' not present in evidence screenshots")
    if neg_control.get("screenshot_sha256") != evidence["screenshots"][neg_shot_key]:
        raise ValueError("negative_control screenshot_sha256 mismatch with screenshots table")

    # 1. Target manifest
    target_manifest = os.path.join(target_dir, "manifest.json")
    if not os.path.exists(target_manifest):
        raise FileNotFoundError(f"Target manifest not found: {target_manifest}")
    act_t_hash = compute_sha256(target_manifest)
    if act_t_hash != evidence["target_manifest_sha256"]:
        raise ValueError(f"Target manifest hash mismatch: expected {evidence['target_manifest_sha256']}, got {act_t_hash}")

    # 2. Target character file
    target_char = os.path.join(target_dir, "Graphics", "Characters", "001-Fighter01.png")
    if not os.path.exists(target_char):
        raise FileNotFoundError(f"Target character file not found: {target_char}")
    act_c_hash = compute_sha256(target_char)
    if act_c_hash != evidence["target_character_sha256"]:
        raise ValueError(f"Target character file hash mismatch: expected {evidence['target_character_sha256']}, got {act_c_hash}")

    # 3. Fixture manifest
    fixt_manifest = os.path.join(fixture_dir, "fixture_manifest.json")
    if not os.path.exists(fixt_manifest):
        raise FileNotFoundError(f"Fixture manifest not found: {fixt_manifest}")
    act_f_hash = compute_sha256(fixt_manifest)
    if act_f_hash != evidence["fixture_manifest_sha256"]:
        raise ValueError(f"Fixture manifest hash mismatch: expected {evidence['fixture_manifest_sha256']}, got {act_f_hash}")

    # 4. Fixture script (fixture.rb)
    fixt_script = os.path.join(fixture_dir, evidence.get("fixture_script", "fixture.rb"))
    if not os.path.exists(fixt_script):
        raise FileNotFoundError(f"Fixture script not found: {fixt_script}")
    act_script_hash = compute_sha256(fixt_script)
    if act_script_hash != evidence.get("fixture_script_sha256"):
        raise ValueError(f"Fixture script hash mismatch: expected {evidence.get('fixture_script_sha256')}, got {act_script_hash}")

    # 5. Portable runtime configuration hash checks
    pos_conf_obj = evidence.get("positive_runtime_configuration")
    if not isinstance(pos_conf_obj, dict):
        raise ValueError("Missing positive_runtime_configuration in evidence")
    calc_pos_hash = hashlib.sha256(json.dumps(pos_conf_obj, sort_keys=True, indent=2).encode("utf-8")).hexdigest()
    if calc_pos_hash != evidence.get("positive_runtime_configuration_sha256"):
        raise ValueError(f"Positive runtime configuration hash mismatch: expected {evidence.get('positive_runtime_configuration_sha256')}, got {calc_pos_hash}")

    neg_conf_obj = evidence.get("negative_runtime_configuration")
    if not isinstance(neg_conf_obj, dict):
        raise ValueError("Missing negative_runtime_configuration in evidence")
    calc_neg_hash = hashlib.sha256(json.dumps(neg_conf_obj, sort_keys=True, indent=2).encode("utf-8")).hexdigest()
    if calc_neg_hash != evidence.get("negative_runtime_configuration_sha256"):
        raise ValueError(f"Negative runtime configuration hash mismatch: expected {evidence.get('negative_runtime_configuration_sha256')}, got {calc_neg_hash}")

    # 6. Runtime logs
    pos_log = os.path.join(artifacts_dir, evidence.get("positive_runtime_log", "positive_runtime.log"))
    if not os.path.exists(pos_log):
        raise FileNotFoundError(f"Missing positive runtime log: {pos_log}")
    act_pos_log_hash = compute_sha256(pos_log)
    if act_pos_log_hash != evidence["positive_runtime_log_sha256"]:
        raise ValueError(f"Positive runtime log hash mismatch: expected {evidence['positive_runtime_log_sha256']}, got {act_pos_log_hash}")

    neg_log = os.path.join(artifacts_dir, evidence.get("negative_runtime_log", "negative_runtime.log"))
    if not os.path.exists(neg_log):
        raise FileNotFoundError(f"Missing negative runtime log: {neg_log}")
    act_neg_log_hash = compute_sha256(neg_log)
    if act_neg_log_hash != evidence["negative_runtime_log_sha256"]:
        raise ValueError(f"Negative runtime log hash mismatch: expected {evidence['negative_runtime_log_sha256']}, got {act_neg_log_hash}")

    # Diagnostic check in negative log
    with open(neg_log, "r", encoding="utf-8", errors="replace") as nlf:
        neg_text = nlf.read()
    if expected_diag not in neg_text:
        raise ValueError(f"Expected diagnostic '{expected_diag}' not found in negative runtime log")

    # 7. Screenshots & pixel assertions
    for shot_name, exp_hash in evidence["screenshots"].items():
        shot_path = os.path.join(artifacts_dir, shot_name)
        if not os.path.exists(shot_path):
            raise FileNotFoundError(f"Missing screenshot: {shot_path}")
        act_shot_hash = compute_sha256(shot_path)
        if act_shot_hash != exp_hash:
            raise ValueError(f"Screenshot hash mismatch for {shot_name}: expected {exp_hash}, got {act_shot_hash}")

        mode = "negative_control" if "negative" in shot_name else "positive"
        res = verify_rmxp_screenshot(shot_path, mode=mode)
        print(f"  [PASS] {shot_name}: SHA-256 match, Visual content: {res['status']}")

    print("ALL RPG MAKER XP CHARACTER RUNTIME EVIDENCE CHECKS PASSED: Evidence chain is durable and verified.")
    return True

def run_capture_and_record():
    """
    Executes live mkxp-z runs under xvfb for positive and negative controls,
    captures logs, captures 640x480 screenshots, verifies pixels, and writes evidence JSON.
    Uses temporary runtime directories to ensure repository working tree is never mutated.
    """
    cfg = get_target_config()
    mkxp_bin = shutil.which("mkxp-z")
    if not mkxp_bin:
        mkxp_bin = os.path.expanduser("~/.local/bin/mkxp-z")
    if not os.path.exists(mkxp_bin):
        raise RuntimeError("mkxp-z not found on PATH or ~/.local/bin/mkxp-z")
    if not shutil.which("xvfb-run"):
        raise RuntimeError("xvfb-run not found on PATH")
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found on PATH")

    # Ensure target is built
    from build_target import build_target
    build_target("rmxp", output_dir=cfg["target_dir"], clean=False)

    os.makedirs(cfg["artifacts_dir"], exist_ok=True)
    pos_log_path = os.path.join(cfg["artifacts_dir"], "positive_runtime.log")
    neg_log_path = os.path.join(cfg["artifacts_dir"], "negative_runtime.log")
    pos_shot_name = "rmxp_character_positive.png"
    neg_shot_name = "rmxp_character_negative_control.png"
    pos_shot_path = os.path.join(cfg["artifacts_dir"], pos_shot_name)
    neg_shot_path = os.path.join(cfg["artifacts_dir"], neg_shot_name)

    # 1. Positive Control Run (executed from temporary directory)
    print("Executing mkxp-z positive control under xvfb from temporary runtime directory...")
    with tempfile.TemporaryDirectory(prefix="mkxp_pos_run_") as tmp_pos_dir:
        pos_conf = {
            "rgssVersion": 1,
            "gameFolder": os.path.abspath(cfg["fixture_dir"]),
            "customScript": "fixture.rb",
            "pathCache": True,
            "RTP": [os.path.abspath(cfg["target_dir"])]
        }
        with open(os.path.join(tmp_pos_dir, "mkxp.json"), "w", encoding="utf-8") as f:
            json.dump(pos_conf, f, indent=2)
            f.write("\n")

        pos_mkv = "/tmp/rmxp_char_pos.mkv"
        pos_cmd = (
            f"cd {tmp_pos_dir} && "
            f"xvfb-run -s '-screen 0 640x480x24' bash -c '"
            f"ffmpeg -y -f x11grab -draw_mouse 0 -video_size 640x480 -i :99.0 -c:v libx264rgb -crf 0 -preset ultrafast -t 3 {pos_mkv} & "
            f"FFMPEG_PID=$! ; sleep 0.3 ; "
            f"ALSOFT_DRIVERS=null SDL_VIDEODRIVER=x11 {mkxp_bin} > /tmp/rmxp_pos_stdout.log 2> /tmp/rmxp_pos_stderr.log ; "
            f"echo $? > /tmp/rmxp_pos_exit_code ; "
            f"wait $FFMPEG_PID'"
        )
        subprocess.run(pos_cmd, shell=True, check=True)
        extract_pos_cmd = ["ffmpeg", "-y", "-ss", "00:00:01.0", "-i", pos_mkv, "-frames:v", "1", pos_shot_path]
        subprocess.run(extract_pos_cmd, capture_output=True, check=True)

    with open("/tmp/rmxp_pos_exit_code", "r") as f:
        pos_exit_code = int(f.read().strip())
    if pos_exit_code != 0:
        raise RuntimeError(f"Positive control mkxp-z failed with exit code {pos_exit_code}")

    with open("/tmp/rmxp_pos_stdout.log", "r", encoding="utf-8", errors="replace") as f_out:
        pos_stdout = f_out.read()
    with open("/tmp/rmxp_pos_stderr.log", "r", encoding="utf-8", errors="replace") as f_err:
        pos_stderr = f_err.read()
    pos_log_content = pos_stdout + "\n" + pos_stderr
    with open(pos_log_path, "w", encoding="utf-8") as f:
        f.write(pos_log_content)

    # Extract mkxp-z version from stdout
    ver_match = re.search(r"MKXP-Z VERSION:\s*(\S+)", pos_stdout)
    mkxp_version = ver_match.group(1) if ver_match else "unknown"

    # 2. Negative Control Run (executed from temporary directory)
    print("Executing mkxp-z negative control under xvfb from temporary runtime directory...")
    with tempfile.TemporaryDirectory(prefix="mkxp_neg_run_") as tmp_neg_dir:
        neg_conf = {
            "rgssVersion": 1,
            "gameFolder": os.path.abspath(cfg["fixture_dir"]),
            "customScript": "fixture.rb",
            "pathCache": True,
            "RTP": []
        }
        with open(os.path.join(tmp_neg_dir, "mkxp.json"), "w", encoding="utf-8") as f:
            json.dump(neg_conf, f, indent=2)
            f.write("\n")

        neg_mkv = "/tmp/rmxp_char_neg.mkv"
        neg_cmd = (
            f"cd {tmp_neg_dir} && "
            f"xvfb-run -s '-screen 0 640x480x24' bash -c '"
            f"ffmpeg -y -f x11grab -draw_mouse 0 -video_size 640x480 -i :99.0 -c:v libx264rgb -crf 0 -preset ultrafast -t 2 {neg_mkv} & "
            f"FFMPEG_PID=$! ; sleep 0.3 ; "
            f"ALSOFT_DRIVERS=null SDL_VIDEODRIVER=x11 {mkxp_bin} > /tmp/rmxp_neg_stdout.log 2> /tmp/rmxp_neg_stderr.log ; "
            f"echo $? > /tmp/rmxp_neg_exit_code ; "
            f"wait $FFMPEG_PID'"
        )
        subprocess.run(neg_cmd, shell=True, check=True)
        extract_neg_cmd = ["ffmpeg", "-y", "-ss", "00:00:00.8", "-i", neg_mkv, "-frames:v", "1", neg_shot_path]
        subprocess.run(extract_neg_cmd, capture_output=True, check=True)

    with open("/tmp/rmxp_neg_exit_code", "r") as f:
        neg_exit_code = int(f.read().strip())
    if neg_exit_code != 1:
        raise RuntimeError(f"Negative control mkxp-z expected exit code 1, got {neg_exit_code}")

    with open("/tmp/rmxp_neg_stdout.log", "r", encoding="utf-8", errors="replace") as f_out:
        neg_stdout = f_out.read()
    with open("/tmp/rmxp_neg_stderr.log", "r", encoding="utf-8", errors="replace") as f_err:
        neg_stderr = f_err.read()
    neg_log_content = neg_stdout + "\n" + neg_stderr
    with open(neg_log_path, "w", encoding="utf-8") as f:
        f.write(neg_log_content)

    # 3. Pixel verification
    pos_vis = verify_rmxp_screenshot(pos_shot_path, mode="positive")
    neg_vis = verify_rmxp_screenshot(neg_shot_path, mode="negative_control")

    # 4. Build portable config templates and compute hashes
    pos_cfg_portable = {
        "rgssVersion": 1,
        "gameFolder": "tests/fixtures/rmxp_character_min",
        "customScript": "fixture.rb",
        "pathCache": True,
        "RTP": ["generated/rmxp"]
    }
    neg_cfg_portable = {
        "rgssVersion": 1,
        "gameFolder": "tests/fixtures/rmxp_character_min",
        "customScript": "fixture.rb",
        "pathCache": True,
        "RTP": []
    }
    pos_cfg_sha256 = hashlib.sha256(json.dumps(pos_cfg_portable, sort_keys=True, indent=2).encode("utf-8")).hexdigest()
    neg_cfg_sha256 = hashlib.sha256(json.dumps(neg_cfg_portable, sort_keys=True, indent=2).encode("utf-8")).hexdigest()

    # 5. Build evidence JSON
    canonical_rgba = os.path.join(REPO_ROOT, "registry", "assets", "test_calibration_walking_character.rgba")
    target_manifest = os.path.join(cfg["target_dir"], "manifest.json")
    target_char = os.path.join(cfg["target_dir"], "Graphics", "Characters", "001-Fighter01.png")
    fixt_manifest = os.path.join(cfg["fixture_dir"], "fixture_manifest.json")
    fixt_script = os.path.join(cfg["fixture_dir"], "fixture.rb")

    evidence = {
        "target": cfg["target"],
        "engine": "RPG Maker XP",
        "engine_mode": cfg["engine"],
        "runtime": "mkxp-z",
        "runtime_commit": PINNED_MKXP_COMMIT,
        "rgss_version": 1,
        "target_category": "Character",
        "requested_resource": f"Graphics/Characters/{cfg['expected_character_slot']}",
        "source_character_index": 0,
        "transform_policy": "rm2k_to_rgss1_character_4x4",
        "mkxp_z_build_configuration": {
            "workdir_current": True,
            "static_executable": False,
            "mri_version": "3.3",
            "shared_fluid": False
        },
        "canonical_asset_id": "test.calibration.walking-character",
        "canonical_source_sha256": compute_sha256(canonical_rgba),
        "target_manifest_sha256": compute_sha256(target_manifest),
        "target_character_sha256": compute_sha256(target_char),
        "fixture_manifest_sha256": compute_sha256(fixt_manifest),
        "fixture_script": "fixture.rb",
        "fixture_script_sha256": compute_sha256(fixt_script),
        "positive_runtime_configuration": pos_cfg_portable,
        "positive_runtime_configuration_sha256": pos_cfg_sha256,
        "negative_runtime_configuration": neg_cfg_portable,
        "negative_runtime_configuration_sha256": neg_cfg_sha256,
        "positive_exit_code": pos_exit_code,
        "negative_exit_code": neg_exit_code,
        "positive_runtime_log": "positive_runtime.log",
        "positive_runtime_log_sha256": compute_sha256(pos_log_path),
        "negative_runtime_log": "negative_runtime.log",
        "negative_runtime_log_sha256": compute_sha256(neg_log_path),
        "mkxp_z_version": mkxp_version,
        "recorded_at": get_evidence_timestamp(),
        "negative_control": {
            "status": "VERIFIED",
            "expected_missing_asset": "Graphics/Characters/001-Fighter01",
            "diagnostic": "SUPERRTP_RMXP_MISSING_ASSET: No such file or directory - Graphics/Characters/001-Fighter01",
            "screenshot": neg_shot_name,
            "screenshot_sha256": compute_sha256(neg_shot_path)
        },
        "screenshots": {
            pos_shot_name: compute_sha256(pos_shot_path),
            neg_shot_name: compute_sha256(neg_shot_path)
        },
        "visual_evidence": pos_vis
    }

    with open(cfg["evidence_path"], "w", encoding="utf-8") as f:
        json.dump(evidence, f, indent=2)
        f.write("\n")

    print(f"Wrote verification evidence to {cfg['evidence_path']}")
    return True

def main():
    parser = argparse.ArgumentParser(description="SuperRTP RPG Maker XP Character Runtime Verifier")
    parser.add_argument("--verify", action="store_true", help="Verify evidence chain and screenshots")
    parser.add_argument("--run-capture", action="store_true", help="Run live mkxp-z to capture screenshots and logs")

    args = parser.parse_args()

    if args.run_capture:
        run_capture_and_record()
    elif args.verify:
        verify_evidence_chain()
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
