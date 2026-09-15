#!/usr/bin/env python3
"""
SuperRTP Deterministic RPG Maker VX Ace (RGSS3) Character Runtime & Visual Verification Tool.

Verifies and reproduces mkxp-z runtime execution for RGSS3 Character compatibility:
  - Executes mkxp-z with clean-room RGSS3 test fixture (rmvxace_character_min)
  - Validates positive control (SuperRTP provides Graphics/Characters/Actor1.png via RTP)
  - Validates negative control (empty RTP isolates missing Actor1.png)
  - Checks startup log banner: "RGSS version 3 (RPG Maker VX Ace) "
  - Inspects rendered 544x416 screenshot pixels for:
      * Test pad geometry (116, 68, 312x280) and 4 corner alignment markers
      * Background color outside pad: (25, 25, 30)
      * Native 1:1 scale sprite placement at (128, 80)
      * Full 288x256 pixel composite equality:
          - Alpha 255 pixels equal Character bitmap RGB
          - Alpha 0 pixels expose contrasting pad color (210, 215, 220)
      * Placement and directional layout of all 8 character blocks:
          - Characters 0..3 in top row (y=80)
          - Characters 4..7 in bottom row (y=208)
          - Rows within each character: DOWN, LEFT, RIGHT, UP
          - Columns: STEP_LEFT, IDLE, STEP_RIGHT
  - Validates explicit byte equality between RMVX and RMVXAce Actor1.png
  - Manages artifacts/runtime/rmvxace/character/verification_evidence.json
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

from verify_rmvx_runtime import verify_vx_family_screenshot, read_mkxp_build_metadata, compute_sha256, get_evidence_timestamp

PINNED_MKXP_COMMIT = "826929eeb3ebc4b887c011604919217a790770f4"

def get_target_config():
    return {
        "target": "rmvxace",
        "engine": "RPG Maker VX Ace",
        "engine_mode": "rgss3",
        "rgss_version": 3,
        "category": "Character",
        "expected_character_slot": "Actor1",
        "transform_policy": "rm2k8_to_rgss3_standard_character_sheet_v1",
        "fixture_dir": os.path.join(REPO_ROOT, "tests", "fixtures", "rmvxace_character_min"),
        "target_dir": os.path.join(REPO_ROOT, "generated", "rmvxace"),
        "rmvx_target_dir": os.path.join(REPO_ROOT, "generated", "rmvx"),
        "artifacts_dir": os.path.join(REPO_ROOT, "artifacts", "runtime", "rmvxace", "character"),
        "evidence_path": os.path.join(REPO_ROOT, "artifacts", "runtime", "rmvxace", "character", "verification_evidence.json"),
    }

def run_capture(cfg):
    """Executes live mkxp-z RGSS3 runtime under Xvfb and captures positive and negative controls."""
    mkxp_bin = shutil.which("mkxp-z") or os.path.expanduser("~/.local/bin/mkxp-z")
    if not os.path.exists(mkxp_bin) or not os.access(mkxp_bin, os.X_OK):
        raise FileNotFoundError(f"mkxp-z executable not found or not executable at '{mkxp_bin}'. Run tools/install_mkxp_z_ci.sh first.")

    os.makedirs(cfg["artifacts_dir"], exist_ok=True)
    pos_shot_name = "rmvxace_character_positive.png"
    neg_shot_name = "rmvxace_character_negative_control.png"
    pos_shot_path = os.path.join(cfg["artifacts_dir"], pos_shot_name)
    neg_shot_path = os.path.join(cfg["artifacts_dir"], neg_shot_name)
    pos_log_path = os.path.join(cfg["artifacts_dir"], "positive_runtime.log")
    neg_log_path = os.path.join(cfg["artifacts_dir"], "negative_runtime.log")

    # 1. Positive Control Run (executed from temporary directory to protect working tree)
    print("Executing mkxp-z RGSS3 positive control under xvfb from temporary runtime directory...")
    with tempfile.TemporaryDirectory(prefix="mkxp_ace_pos_run_") as tmp_pos_dir:
        pos_conf = {
            "rgssVersion": 3,
            "gameFolder": os.path.abspath(cfg["fixture_dir"]),
            "customScript": "fixture.rb",
            "pathCache": True,
            "RTP": [os.path.abspath(cfg["target_dir"])]
        }
        with open(os.path.join(tmp_pos_dir, "mkxp.json"), "w", encoding="utf-8") as f:
            json.dump(pos_conf, f, indent=2)
            f.write("\n")

        pos_mkv = "/tmp/rmvxace_char_pos.mkv"
        pos_cmd = (
            f"cd {tmp_pos_dir} && "
            f"xvfb-run -s '-screen 0 544x416x24' bash -c '"
            f"ffmpeg -y -f x11grab -draw_mouse 0 -video_size 544x416 -i :99.0 -c:v libx264rgb -crf 0 -preset ultrafast -t 3 {pos_mkv} & "
            f"FFMPEG_PID=$! ; sleep 0.3 ; "
            f"SDL_AUDIODRIVER=dummy ALSOFT_DRIVERS=null SDL_VIDEODRIVER=x11 LIBGL_ALWAYS_SOFTWARE=1 {mkxp_bin} > /tmp/rmvxace_pos_stdout.log 2> /tmp/rmvxace_pos_stderr.log ; "
            f"echo $? > /tmp/rmvxace_pos_exit_code ; "
            f"wait $FFMPEG_PID'"
        )
        subprocess.run(pos_cmd, shell=True, check=True)
        extract_pos_cmd = ["ffmpeg", "-y", "-ss", "00:00:01.0", "-i", pos_mkv, "-frames:v", "1", pos_shot_path]
        subprocess.run(extract_pos_cmd, capture_output=True, check=True)

    with open("/tmp/rmvxace_pos_exit_code", "r") as f:
        pos_exit_code = int(f.read().strip())
    if pos_exit_code != 0:
        raise RuntimeError(f"Positive control mkxp-z failed with exit code {pos_exit_code}")

    with open("/tmp/rmvxace_pos_stdout.log", "r", encoding="utf-8", errors="replace") as f_out:
        pos_stdout = f_out.read()
    with open("/tmp/rmvxace_pos_stderr.log", "r", encoding="utf-8", errors="replace") as f_err:
        pos_stderr = f_err.read()
    pos_log_content = pos_stdout + "\n" + pos_stderr
    with open(pos_log_path, "w", encoding="utf-8") as f:
        f.write(pos_log_content)

    # Extract mkxp-z version from stdout
    ver_match = re.search(r"MKXP-Z VERSION:\s*(\S+)", pos_stdout)
    mkxp_version = ver_match.group(1) if ver_match else "unknown"

    # 2. Negative Control Run (executed from temporary directory)
    print("Executing mkxp-z RGSS3 negative control under xvfb from temporary runtime directory...")
    with tempfile.TemporaryDirectory(prefix="mkxp_ace_neg_run_") as tmp_neg_dir:
        neg_conf = {
            "rgssVersion": 3,
            "gameFolder": os.path.abspath(cfg["fixture_dir"]),
            "customScript": "fixture.rb",
            "pathCache": True,
            "RTP": []
        }
        with open(os.path.join(tmp_neg_dir, "mkxp.json"), "w", encoding="utf-8") as f:
            json.dump(neg_conf, f, indent=2)
            f.write("\n")

        neg_mkv = "/tmp/rmvxace_char_neg.mkv"
        neg_cmd = (
            f"cd {tmp_neg_dir} && "
            f"xvfb-run -s '-screen 0 544x416x24' bash -c '"
            f"ffmpeg -y -f x11grab -draw_mouse 0 -video_size 544x416 -i :99.0 -c:v libx264rgb -crf 0 -preset ultrafast -t 2 {neg_mkv} & "
            f"FFMPEG_PID=$! ; sleep 0.3 ; "
            f"SDL_AUDIODRIVER=dummy ALSOFT_DRIVERS=null SDL_VIDEODRIVER=x11 LIBGL_ALWAYS_SOFTWARE=1 {mkxp_bin} > /tmp/rmvxace_neg_stdout.log 2> /tmp/rmvxace_neg_stderr.log ; "
            f"echo $? > /tmp/rmvxace_neg_exit_code ; "
            f"wait $FFMPEG_PID'"
        )
        subprocess.run(neg_cmd, shell=True, check=True)
        extract_neg_cmd = ["ffmpeg", "-y", "-ss", "00:00:00.8", "-i", neg_mkv, "-frames:v", "1", neg_shot_path]
        subprocess.run(extract_neg_cmd, capture_output=True, check=True)

    with open("/tmp/rmvxace_neg_exit_code", "r") as f:
        neg_exit_code = int(f.read().strip())
    if neg_exit_code != 1:
        raise RuntimeError(f"Negative control expected exit code 1 (missing asset), got {neg_exit_code}")

    with open("/tmp/rmvxace_neg_stdout.log", "r", encoding="utf-8", errors="replace") as f_out:
        neg_stdout = f_out.read()
    with open("/tmp/rmvxace_neg_stderr.log", "r", encoding="utf-8", errors="replace") as f_err:
        neg_stderr = f_err.read()
    neg_log_content = neg_stdout + "\n" + neg_stderr
    with open(neg_log_path, "w", encoding="utf-8") as f:
        f.write(neg_log_content)

    # 3. Read and strictly validate mkxp-z build metadata
    build_metadata = read_mkxp_build_metadata(mkxp_bin)

    # 4. Check startup log banner and diagnostic messages
    if "RGSS version 3 (RPG Maker VX Ace)" not in pos_log_content:
        raise ValueError("Positive log missing expected RGSS3 startup banner: 'RGSS version 3 (RPG Maker VX Ace)'")
    if "SUPERRTP_RGSS3_SCREEN 544x416" not in pos_stdout:
        raise ValueError("Positive log missing expected SUPERRTP_RGSS3_SCREEN 544x416 marker")
    if "SUPERRTP_RMVXACE_CHARACTER_LOADED 288x256" not in pos_stdout:
        raise ValueError("Positive log missing expected SUPERRTP_RMVXACE_CHARACTER_LOADED 288x256 marker")
    if "SUPERRTP_RMVXACE_RENDER_DONE" not in pos_stdout:
        raise ValueError("Positive log missing expected SUPERRTP_RMVXACE_RENDER_DONE marker")

    diag_match = re.search(r"SUPERRTP_RMVXACE_MISSING_ASSET:\s*(.+)", neg_log_content)
    if not diag_match:
        raise ValueError("Negative log missing expected SUPERRTP_RMVXACE_MISSING_ASSET diagnostic marker")
    neg_diagnostic = diag_match.group(1).strip()
    if "Graphics/Characters/Actor1" not in neg_diagnostic:
        raise ValueError(f"Negative diagnostic does not mention Graphics/Characters/Actor1: {neg_diagnostic}")

    # 5. Verify pixel compositing
    target_char_path = os.path.join(cfg["target_dir"], "Graphics", "Characters", "Actor1.png")
    pos_vis = verify_vx_family_screenshot(pos_shot_path, target_char_path=target_char_path, mode="positive")
    neg_vis = verify_vx_family_screenshot(neg_shot_path, mode="negative_control")

    # 6. Verify cross-target byte-equality between rmvx and rmvxace
    rmvx_char_path = os.path.join(cfg["rmvx_target_dir"], "Graphics", "Characters", "Actor1.png")
    if not os.path.exists(rmvx_char_path):
        raise FileNotFoundError(f"Reference RMVX character file not found at {rmvx_char_path}")

    with open(target_char_path, "rb") as f:
        ace_bytes = f.read()
    with open(rmvx_char_path, "rb") as f:
        vx_bytes = f.read()

    if ace_bytes != vx_bytes:
        raise ValueError("Actor1.png bytes in rmvxace do not match rmvx Actor1.png bytes")

    rmvx_actor1_sha256 = hashlib.sha256(vx_bytes).hexdigest()
    rmvxace_actor1_sha256 = hashlib.sha256(ace_bytes).hexdigest()

    # 7. Collect fixture and manifest hashes
    fixture_script = os.path.join(cfg["fixture_dir"], "fixture.rb")
    fixture_manifest = os.path.join(cfg["fixture_dir"], "fixture_manifest.json")
    target_manifest = os.path.join(cfg["target_dir"], "manifest.json")
    canonical_rgba = os.path.join(REPO_ROOT, "registry", "assets", "test_calibration_walking_character.rgba")

    # Portable configs
    portable_pos_conf = {
        "rgssVersion": 3,
        "gameFolder": "tests/fixtures/rmvxace_character_min",
        "customScript": "fixture.rb",
        "pathCache": True,
        "RTP": ["generated/rmvxace"]
    }
    portable_neg_conf = {
        "rgssVersion": 3,
        "gameFolder": "tests/fixtures/rmvxace_character_min",
        "customScript": "fixture.rb",
        "pathCache": True,
        "RTP": []
    }

    evidence = {
        "target": cfg["target"],
        "engine": cfg["engine"],
        "engine_mode": cfg["engine_mode"],
        "rgss_version": cfg["rgss_version"],
        "runtime": "mkxp-z",
        "runtime_commit": PINNED_MKXP_COMMIT,
        "startup_log_identity": "RGSS version 3 (RPG Maker VX Ace) ",
        "category": cfg["category"],
        "requested_resource": "Graphics/Characters/Actor1",
        "canonical_asset_id": "test.calibration.walking-character",
        "canonical_asset_sha256": compute_sha256(canonical_rgba),
        "source_character_indices": [0, 1, 2, 3, 4, 5, 6, 7],
        "transform_policy": cfg["transform_policy"],
        "target_manifest_sha256": compute_sha256(target_manifest),
        "actor1_png_sha256": rmvxace_actor1_sha256,
        "rmvx_actor1_reference_sha256": rmvx_actor1_sha256,
        "rmvx_byte_equality": "IDENTICAL",
        "fixture_script_sha256": compute_sha256(fixture_script),
        "fixture_manifest_sha256": compute_sha256(fixture_manifest),
        "positive_portable_config": portable_pos_conf,
        "positive_portable_config_sha256": hashlib.sha256(json.dumps(portable_pos_conf, sort_keys=True).encode("utf-8")).hexdigest(),
        "negative_portable_config": portable_neg_conf,
        "negative_portable_config_sha256": hashlib.sha256(json.dumps(portable_neg_conf, sort_keys=True).encode("utf-8")).hexdigest(),
        "positive_exit_code": pos_exit_code,
        "negative_exit_code": neg_exit_code,
        "positive_runtime_log_sha256": compute_sha256(pos_log_path),
        "negative_runtime_log_sha256": compute_sha256(neg_log_path),
        "negative_diagnostic": neg_diagnostic,
        "positive_screenshot_sha256": compute_sha256(pos_shot_path),
        "negative_screenshot_sha256": compute_sha256(neg_shot_path),
        "positive_visual_verification": pos_vis,
        "negative_visual_verification": neg_vis,
        "build_metadata": build_metadata,
        "timestamp": get_evidence_timestamp()
    }

    with open(cfg["evidence_path"], "w", encoding="utf-8") as f:
        json.dump(evidence, f, indent=2)
        f.write("\n")

    print(f"Successfully generated and verified runtime evidence: {cfg['evidence_path']}")
    return evidence

def verify_evidence_chain(custom_evidence_path=None):
    """Mechanically verifies the recorded evidence chain and asserts pixel correctness."""
    cfg = get_target_config()
    ev_path = custom_evidence_path or cfg["evidence_path"]
    if not os.path.exists(ev_path):
        raise FileNotFoundError(f"Verification evidence not found: {ev_path}")

    with open(ev_path, "r", encoding="utf-8") as f:
        ev = json.load(f)

    # 1. Verify target identity
    if ev.get("target") != "rmvxace":
        raise ValueError(f"Evidence target mismatch: expected 'rmvxace', got {ev.get('target')}")
    if ev.get("engine") != "RPG Maker VX Ace":
        raise ValueError(f"Evidence engine mismatch: expected 'RPG Maker VX Ace', got {ev.get('engine')}")
    if ev.get("engine_mode") != "rgss3":
        raise ValueError(f"Evidence engine_mode mismatch: expected 'rgss3', got {ev.get('engine_mode')}")
    if ev.get("rgss_version") != 3:
        raise ValueError(f"Evidence rgss_version mismatch: expected 3, got {ev.get('rgss_version')}")
    if ev.get("runtime") != "mkxp-z":
        raise ValueError(f"Evidence runtime mismatch: expected 'mkxp-z', got {ev.get('runtime')}")
    if ev.get("runtime_commit") != PINNED_MKXP_COMMIT:
        raise ValueError(f"Evidence runtime_commit mismatch: expected '{PINNED_MKXP_COMMIT}', got {ev.get('runtime_commit')}")
    if ev.get("startup_log_identity") != "RGSS version 3 (RPG Maker VX Ace) ":
        raise ValueError(f"Evidence startup_log_identity mismatch: {ev.get('startup_log_identity')}")
    if ev.get("category") != "Character":
        raise ValueError(f"Evidence category mismatch: expected 'Character', got {ev.get('category')}")
    if ev.get("requested_resource") != "Graphics/Characters/Actor1":
        raise ValueError(f"Evidence requested_resource mismatch: expected 'Graphics/Characters/Actor1', got {ev.get('requested_resource')}")
    if ev.get("source_character_indices") != [0, 1, 2, 3, 4, 5, 6, 7]:
        raise ValueError(f"Evidence source_character_indices mismatch: {ev.get('source_character_indices')}")
    if ev.get("transform_policy") != "rm2k8_to_rgss3_standard_character_sheet_v1":
        raise ValueError(f"Evidence transform_policy mismatch: {ev.get('transform_policy')}")
    if ev.get("rmvx_byte_equality") != "IDENTICAL":
        raise ValueError(f"Evidence rmvx_byte_equality mismatch: {ev.get('rmvx_byte_equality')}")

    # 2. Verify build metadata
    b_meta = ev.get("build_metadata", {})
    if not isinstance(b_meta, dict):
        raise ValueError("Evidence build_metadata must be a dictionary")
    if b_meta.get("runtime") != "mkxp-z":
        raise ValueError(f"Invalid runtime in build metadata: expected 'mkxp-z', got {b_meta.get('runtime')}")
    if b_meta.get("pinned_commit") != PINNED_MKXP_COMMIT:
        raise ValueError(f"Invalid pinned_commit in build metadata: expected '{PINNED_MKXP_COMMIT}', got {b_meta.get('pinned_commit')}")
    if b_meta.get("workdir_current") is not True:
        raise ValueError(f"Invalid workdir_current in build metadata: expected true, got {b_meta.get('workdir_current')}")
    if b_meta.get("static_executable") is not False:
        raise ValueError(f"Invalid static_executable in build metadata: expected false, got {b_meta.get('static_executable')}")
    if b_meta.get("shared_fluid") is not False:
        raise ValueError(f"Invalid shared_fluid in build metadata: expected false, got {b_meta.get('shared_fluid')}")
    if b_meta.get("build_config_revision") != "buildcfg2":
        raise ValueError(f"Invalid build_config_revision in build metadata: expected 'buildcfg2', got {b_meta.get('build_config_revision')}")
    mri_ver = b_meta.get("mri_version")
    if not mri_ver or not isinstance(mri_ver, str) or len(mri_ver.strip()) == 0:
        raise ValueError(f"Invalid or empty mri_version in build metadata: {mri_ver}")

    # 3. Verify canonical source hash
    canonical_rgba = os.path.join(REPO_ROOT, "registry", "assets", "test_calibration_walking_character.rgba")
    if compute_sha256(canonical_rgba) != ev["canonical_asset_sha256"]:
        raise ValueError("Canonical source asset hash mismatch")

    # 4. Verify target manifest and Actor1 hash
    target_manifest = os.path.join(cfg["target_dir"], "manifest.json")
    if compute_sha256(target_manifest) != ev["target_manifest_sha256"]:
        raise ValueError("Target manifest hash mismatch")

    target_char = os.path.join(cfg["target_dir"], "Graphics", "Characters", "Actor1.png")
    if compute_sha256(target_char) != ev["actor1_png_sha256"]:
        raise ValueError("Actor1.png hash mismatch")

    # Verify byte-equality with RMVX Actor1.png
    rmvx_char = os.path.join(cfg["rmvx_target_dir"], "Graphics", "Characters", "Actor1.png")
    if compute_sha256(rmvx_char) != ev["rmvx_actor1_reference_sha256"]:
        raise ValueError("Reference RMVX Actor1.png hash mismatch")
    if ev["actor1_png_sha256"] != ev["rmvx_actor1_reference_sha256"]:
        raise ValueError("Actor1 SHA does not equal RMVX reference SHA in evidence")

    # 5. Verify fixture files
    fixture_script = os.path.join(cfg["fixture_dir"], "fixture.rb")
    fixture_manifest = os.path.join(cfg["fixture_dir"], "fixture_manifest.json")
    if compute_sha256(fixture_script) != ev["fixture_script_sha256"]:
        raise ValueError("Fixture script hash mismatch")
    if compute_sha256(fixture_manifest) != ev["fixture_manifest_sha256"]:
        raise ValueError("Fixture manifest hash mismatch")

    # 6. Verify portable configs
    pos_conf_sha = hashlib.sha256(json.dumps(ev["positive_portable_config"], sort_keys=True).encode("utf-8")).hexdigest()
    if pos_conf_sha != ev["positive_portable_config_sha256"]:
        raise ValueError("Positive portable config hash mismatch")
    if ev["positive_portable_config"].get("rgssVersion") != 3:
        raise ValueError(f"Positive config rgssVersion must be 3, got {ev['positive_portable_config'].get('rgssVersion')}")

    neg_conf_sha = hashlib.sha256(json.dumps(ev["negative_portable_config"], sort_keys=True).encode("utf-8")).hexdigest()
    if neg_conf_sha != ev["negative_portable_config_sha256"]:
        raise ValueError("Negative portable config hash mismatch")
    if ev["negative_portable_config"].get("rgssVersion") != 3:
        raise ValueError(f"Negative config rgssVersion must be 3, got {ev['negative_portable_config'].get('rgssVersion')}")

    # 7. Verify exit codes and logs
    if ev.get("positive_exit_code") != 0:
        raise ValueError(f"Expected positive exit code 0, got {ev.get('positive_exit_code')}")
    if ev.get("negative_exit_code") != 1:
        raise ValueError(f"Expected negative exit code 1, got {ev.get('negative_exit_code')}")

    pos_log_path = os.path.join(cfg["artifacts_dir"], "positive_runtime.log")
    if compute_sha256(pos_log_path) != ev["positive_runtime_log_sha256"]:
        raise ValueError("Positive runtime log hash mismatch")

    neg_log_path = os.path.join(cfg["artifacts_dir"], "negative_runtime.log")
    if compute_sha256(neg_log_path) != ev["negative_runtime_log_sha256"]:
        raise ValueError("Negative runtime log hash mismatch")

    with open(neg_log_path, "r", encoding="utf-8") as f:
        neg_log_content = f.read()
    if ev["negative_diagnostic"] not in neg_log_content:
        raise ValueError("Negative diagnostic not found in negative runtime log")
    if "Graphics/Characters/Actor1" not in ev["negative_diagnostic"]:
        raise ValueError("Negative diagnostic does not mention Graphics/Characters/Actor1")

    # 8. Verify screenshots and pixel content
    pos_shot_path = os.path.join(cfg["artifacts_dir"], "rmvxace_character_positive.png")
    if compute_sha256(pos_shot_path) != ev["positive_screenshot_sha256"]:
        raise ValueError("Positive screenshot hash mismatch")

    neg_shot_path = os.path.join(cfg["artifacts_dir"], "rmvxace_character_negative_control.png")
    if compute_sha256(neg_shot_path) != ev["negative_screenshot_sha256"]:
        raise ValueError("Negative screenshot hash mismatch")

    # Pixel inspection
    verify_vx_family_screenshot(pos_shot_path, target_char_path=target_char, mode="positive")
    verify_vx_family_screenshot(neg_shot_path, mode="negative_control")

    print("ALL RUNTIME EVIDENCE CHECKS PASSED: Evidence chain is durable and verified.")
    return 0

def main():
    parser = argparse.ArgumentParser(description="SuperRTP RPG Maker VX Ace Runtime Verifier")
    parser.add_argument("--run-capture", action="store_true", help="Execute live mkxp-z run and capture screenshots/evidence")
    parser.add_argument("--verify", action="store_true", help="Verify existing evidence chain and screenshot pixels")
    parser.add_argument("--evidence-file", default=None, help="Custom evidence file path")
    args = parser.parse_args()

    cfg = get_target_config()

    if args.run_capture:
        run_capture(cfg)
        verify_evidence_chain()
    elif args.verify:
        verify_evidence_chain(args.evidence_file)
    else:
        # Default action: verify
        verify_evidence_chain(args.evidence_file)

if __name__ == "__main__":
    main()
