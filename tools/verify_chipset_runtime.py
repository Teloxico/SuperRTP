#!/usr/bin/env python3
"""
SuperRTP Deterministic ChipSet Runtime & Visual Verification Tool.

Verifies and reproduces EasyRPG Player runtime execution for ChipSet compatibility:
  - Executes EasyRPG with RM2000 and RM2003 ChipSet minimal game fixtures
  - Validates positive control (SuperRTP provides World.png / Basis.png / Main.png)
  - Validates negative control (--no-rtp isolates missing ChipSet/Basis or ChipSet/Main)
  - Inspects rendered tile coordinates for Block E Bank 1 (5000), Block E Bank 2 (5096),
    Block F Bank 2 (10048), and Block F Bank 1 composited over Block E (10000 over 5000)
  - Validates transparency and layer composition mechanics deterministically
  - Manages artifacts/runtime/<target>/chipset/verification_evidence.json
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
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

from png_utils import decode_png_rgb

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

def get_target_config(target="rm2000"):
    is_2k3 = (target in ("rm2003", "2k3"))
    norm_target = "rm2003" if is_2k3 else "rm2000"
    engine = "rpg2k3" if is_2k3 else "rpg2k"
    alias = "Main" if is_2k3 else "Basis"

    return {
        "target": norm_target,
        "engine": engine,
        "expected_chipset_alias": alias,
        "fixture_dir": os.path.join(REPO_ROOT, "tests", "fixtures", f"{norm_target}_chipset_min"),
        "target_dir": os.path.join(REPO_ROOT, "generated", norm_target),
        "artifacts_dir": os.path.join(REPO_ROOT, "artifacts", "runtime", norm_target, "chipset"),
        "evidence_path": os.path.join(REPO_ROOT, "artifacts", "runtime", norm_target, "chipset", "verification_evidence.json"),
    }

def verify_chipset_screenshot(screenshot_path, mode="positive", target="rm2000"):
    """
    Deterministically inspects pixels of the captured 640x480 screenshot.
    Screen resolution: 320x240 native scaled 2x to 640x480.
    """
    if not os.path.exists(screenshot_path):
        raise FileNotFoundError(f"Screenshot not found: {screenshot_path}")

    w, h, pixels = decode_png_rgb(screenshot_path)
    if w != 640 or h != 480:
        raise ValueError(f"Expected 640x480 screenshot, got {w}x{h}")

    if mode == "negative_control":
        # In negative control, ChipSet failed to load.
        # Ensure tile 5000 yellow center is NOT present at (80, 80).
        c_rgb = pixels[80][80]
        if c_rgb == (255, 220, 30):
            raise ValueError(f"Negative control unexpectedly rendered valid ChipSet tile 5000 at (80, 80)")
        return {
            "status": "VERIFIED",
            "mode": "negative_control",
            "missing_detected": True,
            "center_color": list(c_rgb)
        }

    # Positive control: verify 4 key test tile regions
    # 1. Tile (2, 2): Block E Bank 1 (Tile 5000)
    # Native: (32..47, 32..47). 2x Scaled: (64..95, 64..95)
    t5000_center = pixels[80][80]      # Center box
    t5000_border = pixels[64][64]      # Border
    t5000_bg = pixels[70][70]          # Background

    expected_5000_center = (255, 220, 30)  # Yellow
    expected_5000_border = (0, 240, 255)   # Cyan
    expected_5000_bg = (12, 48, 160)       # Blue

    if t5000_center != expected_5000_center:
        raise ValueError(f"Tile 5000 center mismatch: expected {expected_5000_center}, got {t5000_center}")
    if t5000_border != expected_5000_border:
        raise ValueError(f"Tile 5000 border mismatch: expected {expected_5000_border}, got {t5000_border}")
    if t5000_bg != expected_5000_bg:
        raise ValueError(f"Tile 5000 bg mismatch: expected {expected_5000_bg}, got {t5000_bg}")

    # 2. Tile (4, 2): Block E Bank 2 (Tile 5096)
    # Native: (64..79, 32..47). 2x Scaled: (128..159, 64..95)
    t5096_center = pixels[80][144]     # Center box
    t5096_border = pixels[64][128]     # Border
    t5096_bg = pixels[70][134]         # Background

    expected_5096_center = (250, 40, 200)  # Magenta
    expected_5096_border = (50, 255, 80)   # Lime
    expected_5096_bg = (15, 120, 45)       # Green

    if t5096_center != expected_5096_center:
        raise ValueError(f"Tile 5096 center mismatch: expected {expected_5096_center}, got {t5096_center}")
    if t5096_border != expected_5096_border:
        raise ValueError(f"Tile 5096 border mismatch: expected {expected_5096_border}, got {t5096_border}")
    if t5096_bg != expected_5096_bg:
        raise ValueError(f"Tile 5096 bg mismatch: expected {expected_5096_bg}, got {t5096_bg}")

    # 3. Tile (6, 2): Block F Bank 2 (Tile 10048) - Upper Layer
    # Native: (96..111, 32..47). 2x Scaled: (192..223, 64..95)
    t10048_center = pixels[80][208]
    expected_10048_center = (255, 130, 10)  # Orange

    if t10048_center != expected_10048_center:
        raise ValueError(f"Tile 10048 center mismatch: expected {expected_10048_center}, got {t10048_center}")

    # 4. Tile (8, 2): Block F Bank 1 (Tile 10000) over Block E Bank 1 (Tile 5000)
    # Native: (128..143, 32..47). 2x Scaled: (256..287, 64..95)
    # Center must show Tile 10000 red cross: (230, 30, 30)
    # Corner (x=256, y=64) must show lower layer Tile 5000 cyan border: (0, 240, 255)
    # Inner corner (x=260, y=68) must show lower layer Tile 5000 blue bg: (12, 48, 160)
    t10000_center = pixels[80][272]
    t10000_comp_corner = pixels[64][256]
    t10000_comp_bg = pixels[68][260]

    expected_10000_center = (230, 30, 30)  # Red cross
    if t10000_center != expected_10000_center:
        raise ValueError(f"Tile 10000 center mismatch: expected {expected_10000_center}, got {t10000_center}")
    if t10000_comp_corner != expected_5000_border:
        raise ValueError(f"Tile 10000/5000 composite corner mismatch: expected {expected_5000_border}, got {t10000_comp_corner}")
    if t10000_comp_bg != expected_5000_bg:
        raise ValueError(f"Tile 10000/5000 composite bg mismatch: expected {expected_5000_bg}, got {t10000_comp_bg}")

    return {
        "status": "VERIFIED",
        "mode": "positive",
        "tile_5000": {
            "center": list(t5000_center),
            "border": list(t5000_border),
            "bg": list(t5000_bg)
        },
        "tile_5096": {
            "center": list(t5096_center),
            "border": list(t5096_border),
            "bg": list(t5096_bg)
        },
        "tile_10048": {
            "center": list(t10048_center)
        },
        "tile_10000_over_5000": {
            "upper_center_cross": list(t10000_center),
            "lower_border_through_transparency": list(t10000_comp_corner),
            "lower_bg_through_transparency": list(t10000_comp_bg)
        }
    }

def verify_evidence_chain(target="rm2000", evidence_path=None, artifacts_dir=None, target_dir=None, fixture_dir=None, canonical_rgba_path=None):
    """Verifies complete cryptographic hashes and visual evidence chain for ChipSet."""
    cfg = get_target_config(target)
    if evidence_path is None:
        evidence_path = cfg["evidence_path"]
    if artifacts_dir is None:
        artifacts_dir = cfg["artifacts_dir"]
    if target_dir is None:
        target_dir = cfg["target_dir"]
    if fixture_dir is None:
        fixture_dir = cfg["fixture_dir"]
    if canonical_rgba_path is None:
        canonical_rgba_path = os.path.join(REPO_ROOT, "registry", "assets", "test_calibration_map_chipset.rgba")

    if not os.path.exists(evidence_path):
        raise FileNotFoundError(f"Verification evidence file not found: {evidence_path}")

    with open(evidence_path, "r", encoding="utf-8") as f:
        evidence = json.load(f)

    print(f"=== SuperRTP ChipSet Runtime Verification Evidence Check ({target}) ===")
    print(f"Target:          {evidence.get('target')}")
    print(f"Engine Mode:     {evidence.get('engine_mode')}")
    print(f"Requested Slot:  {evidence.get('requested_chipset')}")
    print(f"Canonical Asset: {evidence.get('canonical_asset_id')}")
    print(f"EasyRPG Version: {evidence.get('easyrpg_version')}")
    print(f"Recorded Date:   {evidence.get('recorded_at')}")

    # Check target and engine mode
    if evidence.get("target") != cfg["target"]:
        raise ValueError(f"Evidence target mismatch: expected {cfg['target']}, got {evidence.get('target')}")
    if evidence.get("engine_mode") != cfg["engine"]:
        raise ValueError(f"Evidence engine_mode mismatch: expected {cfg['engine']}, got {evidence.get('engine_mode')}")

    # Check requested chipset slot alias
    if evidence.get("requested_chipset") != cfg["expected_chipset_alias"]:
        raise ValueError(f"Evidence requested_chipset mismatch: expected {cfg['expected_chipset_alias']}, got {evidence.get('requested_chipset')}")

    # Check canonical asset ID and canonical source SHA-256
    if evidence.get("canonical_asset_id") != "test.calibration.map-chipset":
        raise ValueError(f"Unexpected canonical_asset_id: {evidence.get('canonical_asset_id')}")
    if not os.path.exists(canonical_rgba_path):
        raise FileNotFoundError(f"Canonical RGBA source file missing: {canonical_rgba_path}")
    actual_canonical_sha256 = compute_sha256(canonical_rgba_path)
    if actual_canonical_sha256 != evidence.get("canonical_source_sha256"):
        raise ValueError(f"Canonical source SHA-256 mismatch: expected {evidence.get('canonical_source_sha256')}, got {actual_canonical_sha256}")

    # Check EasyRPG pinned version
    ver = evidence.get("easyrpg_version", "")
    if "0.8.1.1" not in ver:
        raise ValueError(f"EasyRPG version pin violation: expected 0.8.1.1 in '{ver}'")

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
    expected_missing = f"ChipSet/{cfg['expected_chipset_alias']}"
    if neg_control.get("expected_missing_asset") != expected_missing:
        raise ValueError(f"negative_control.expected_missing_asset mismatch: expected '{expected_missing}', got {neg_control.get('expected_missing_asset')}")
    expected_diag = f"Image not found: ChipSet/{cfg['expected_chipset_alias']}"
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

    # 2. Target World.png
    target_world = os.path.join(target_dir, "ChipSet", "World.png")
    if not os.path.exists(target_world):
        raise FileNotFoundError(f"Target World.png not found: {target_world}")
    act_w_hash = compute_sha256(target_world)
    if act_w_hash != evidence["target_world_sha256"]:
        raise ValueError(f"Target World.png hash mismatch: expected {evidence['target_world_sha256']}, got {act_w_hash}")

    # 3. Fixture manifest
    fixt_manifest = os.path.join(fixture_dir, "fixture_manifest.json")
    if not os.path.exists(fixt_manifest):
        raise FileNotFoundError(f"Fixture manifest not found: {fixt_manifest}")
    act_f_hash = compute_sha256(fixt_manifest)
    if act_f_hash != evidence["fixture_manifest_sha256"]:
        raise ValueError(f"Fixture manifest hash mismatch: expected {evidence['fixture_manifest_sha256']}, got {act_f_hash}")

    # 4. Runtime logs
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

    # 5. Screenshots & pixel assertions
    for shot_name, exp_hash in evidence["screenshots"].items():
        shot_path = os.path.join(artifacts_dir, shot_name)
        if not os.path.exists(shot_path):
            raise FileNotFoundError(f"Missing screenshot: {shot_path}")
        act_shot_hash = compute_sha256(shot_path)
        if act_shot_hash != exp_hash:
            raise ValueError(f"Screenshot hash mismatch for {shot_name}: expected {exp_hash}, got {act_shot_hash}")

        mode = "negative_control" if "negative" in shot_name else "positive"
        res = verify_chipset_screenshot(shot_path, mode=mode, target=target)
        print(f"  [PASS] {shot_name}: SHA-256 match, Visual content: {res['status']}")

    print(f"ALL CHIPSET RUNTIME EVIDENCE CHECKS PASSED ({target}): Evidence chain is durable and verified.")
    return True

def run_capture_and_record(target="rm2000"):
    """
    Executes live EasyRPG Player runs under xvfb for positive and negative controls,
    captures logs, captures 640x480 screenshots, verifies pixels, and writes evidence JSON.
    """
    cfg = get_target_config(target)
    player_bin = shutil.which("easyrpg-player")
    if not player_bin:
        raise RuntimeError("easyrpg-player not found on PATH")
    if not shutil.which("xvfb-run"):
        raise RuntimeError("xvfb-run not found on PATH")
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found on PATH")

    # Ensure target is built
    from build_target import build_target
    build_target(cfg["target"], output_dir=cfg["target_dir"], clean=False)

    ver_res = subprocess.run([player_bin, "--version"], capture_output=True, text=True)
    version_line = ver_res.stdout.splitlines()[0] if ver_res.stdout else "unknown"

    os.makedirs(cfg["artifacts_dir"], exist_ok=True)
    pos_log_path = os.path.join(cfg["artifacts_dir"], "positive_runtime.log")
    neg_log_path = os.path.join(cfg["artifacts_dir"], "negative_runtime.log")
    pos_shot_name = f"{cfg['target']}_chipset_positive.png"
    neg_shot_name = f"{cfg['target']}_chipset_negative_control.png"
    pos_shot_path = os.path.join(cfg["artifacts_dir"], pos_shot_name)
    neg_shot_path = os.path.join(cfg["artifacts_dir"], neg_shot_name)

    # 1. Positive Control Run
    print(f"Executing EasyRPG positive control for {cfg['target']} under xvfb...")
    pos_mkv = f"/tmp/easyrpg_chipset_pos_{cfg['target']}.mkv"
    pos_cmd = (
        f"xvfb-run -s '-screen 0 640x480x24' bash -c '"
        f"ffmpeg -y -f x11grab -draw_mouse 0 -video_size 640x480 -i :99.0 -c:v libx264rgb -crf 0 -preset ultrafast -t 5 {pos_mkv} & "
        f"FFMPEG_PID=$! ; sleep 0.3 ; "
        f"SDL_VIDEODRIVER=x11 {player_bin} --project-path {cfg['fixture_dir']} --rtp-path {cfg['target_dir']} "
        f"--engine {cfg['engine']} --new-game --disable-audio --no-pause-focus-lost --fullscreen "
        f"--no-log-color --seed 42 & "
        f"PLAYER_PID=$! ; wait $FFMPEG_PID ; kill $PLAYER_PID 2>/dev/null || true ; wait $PLAYER_PID 2>/dev/null || true'"
    )
    subprocess.run(pos_cmd, shell=True, check=True)
    extract_pos_cmd = ["ffmpeg", "-y", "-ss", "00:00:03.5", "-i", pos_mkv, "-frames:v", "1", pos_shot_path]
    subprocess.run(extract_pos_cmd, capture_output=True, check=True)

    # Capture positive runtime log separately for complete flush
    pos_log_cmd = [
        player_bin,
        "--project-path", cfg["fixture_dir"],
        "--rtp-path", cfg["target_dir"],
        "--engine", cfg["engine"],
        "--new-game",
        "--disable-audio",
        "--no-pause-focus-lost",
        "--no-log-color",
        "--seed", "42"
    ]
    env_dummy = os.environ.copy()
    env_dummy["SDL_VIDEODRIVER"] = "dummy"
    env_dummy["SDL_AUDIODRIVER"] = "dummy"
    try:
        res = subprocess.run(pos_log_cmd, env=env_dummy, capture_output=True, text=True, timeout=3.5)
        pos_log_content = res.stdout + res.stderr
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b'').decode('utf-8', errors='replace') if isinstance(e.stdout, bytes) else (e.stdout or '')
        err = (e.stderr or b'').decode('utf-8', errors='replace') if isinstance(e.stderr, bytes) else (e.stderr or '')
        pos_log_content = out + err

    with open(pos_log_path, "w", encoding="utf-8") as f:
        f.write(pos_log_content)

    # 2. Negative Control Run
    print(f"Executing EasyRPG negative control for {cfg['target']} under xvfb...")
    neg_mkv = f"/tmp/easyrpg_chipset_neg_{cfg['target']}.mkv"
    neg_cmd = (
        f"xvfb-run -s '-screen 0 640x480x24' bash -c '"
        f"ffmpeg -y -f x11grab -draw_mouse 0 -video_size 640x480 -i :99.0 -c:v libx264rgb -crf 0 -preset ultrafast -t 4 {neg_mkv} & "
        f"FFMPEG_PID=$! ; sleep 0.3 ; "
        f"SDL_VIDEODRIVER=x11 {player_bin} --project-path {cfg['fixture_dir']} --no-rtp "
        f"--engine {cfg['engine']} --new-game --disable-audio --no-pause-focus-lost --fullscreen "
        f"--no-log-color --seed 42 & "
        f"PLAYER_PID=$! ; wait $FFMPEG_PID ; kill $PLAYER_PID 2>/dev/null || true ; wait $PLAYER_PID 2>/dev/null || true'"
    )
    subprocess.run(neg_cmd, shell=True, check=True)
    extract_neg_cmd = ["ffmpeg", "-y", "-ss", "00:00:03.0", "-i", neg_mkv, "-frames:v", "1", neg_shot_path]
    subprocess.run(extract_neg_cmd, capture_output=True, check=True)

    neg_log_cmd = [
        player_bin,
        "--project-path", cfg["fixture_dir"],
        "--no-rtp",
        "--engine", cfg["engine"],
        "--new-game",
        "--disable-audio",
        "--no-pause-focus-lost",
        "--no-log-color",
        "--seed", "42"
    ]
    try:
        res = subprocess.run(neg_log_cmd, env=env_dummy, capture_output=True, text=True, timeout=3.5)
        neg_log_content = res.stdout + res.stderr
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b'').decode('utf-8', errors='replace') if isinstance(e.stdout, bytes) else (e.stdout or '')
        err = (e.stderr or b'').decode('utf-8', errors='replace') if isinstance(e.stderr, bytes) else (e.stderr or '')
        neg_log_content = out + err

    with open(neg_log_path, "w", encoding="utf-8") as f:
        f.write(neg_log_content)

    # 3. Pixel verification
    pos_vis = verify_chipset_screenshot(pos_shot_path, mode="positive", target=cfg["target"])
    neg_vis = verify_chipset_screenshot(neg_shot_path, mode="negative_control", target=cfg["target"])

    # 4. Build evidence JSON
    canonical_rgba = os.path.join(REPO_ROOT, "registry", "assets", "test_calibration_map_chipset.rgba")
    target_manifest = os.path.join(cfg["target_dir"], "manifest.json")
    target_world = os.path.join(cfg["target_dir"], "ChipSet", "World.png")
    fixt_manifest = os.path.join(cfg["fixture_dir"], "fixture_manifest.json")

    evidence = {
        "target": cfg["target"],
        "engine_mode": cfg["engine"],
        "requested_chipset": cfg["expected_chipset_alias"],
        "canonical_asset_id": "test.calibration.map-chipset",
        "canonical_source_sha256": compute_sha256(canonical_rgba),
        "target_manifest_sha256": compute_sha256(target_manifest),
        "target_world_sha256": compute_sha256(target_world),
        "fixture_manifest_sha256": compute_sha256(fixt_manifest),
        "positive_runtime_log": "positive_runtime.log",
        "positive_runtime_log_sha256": compute_sha256(pos_log_path),
        "negative_runtime_log": "negative_runtime.log",
        "negative_runtime_log_sha256": compute_sha256(neg_log_path),
        "easyrpg_version": version_line,
        "recorded_at": get_evidence_timestamp(),
        "negative_control": {
            "status": "VERIFIED",
            "expected_missing_asset": f"ChipSet/{cfg['expected_chipset_alias']}",
            "diagnostic": f"Image not found: ChipSet/{cfg['expected_chipset_alias']}",
            "screenshot": neg_shot_name,
            "screenshot_sha256": compute_sha256(neg_shot_path)
        },
        "screenshots": {
            pos_shot_name: compute_sha256(pos_shot_path),
            neg_shot_name: compute_sha256(neg_shot_path)
        },
        "tile_evidence": pos_vis
    }

    with open(cfg["evidence_path"], "w", encoding="utf-8") as f:
        json.dump(evidence, f, indent=2)
        f.write("\n")

    print(f"Wrote verification evidence to {cfg['evidence_path']}")
    return True

def main():
    parser = argparse.ArgumentParser(description="SuperRTP ChipSet Runtime Verifier")
    parser.add_argument("--verify", action="store_true", help="Verify evidence chain and screenshots")
    parser.add_argument("--run-capture", action="store_true", help="Run live EasyRPG to capture screenshots and logs")
    parser.add_argument("--target", choices=["rm2000", "rm2003", "all"], default="all", help="Target engine")

    args = parser.parse_args()
    targets = ["rm2000", "rm2003"] if args.target == "all" else [args.target]

    if args.run_capture:
        for t in targets:
            run_capture_and_record(t)
    elif args.verify:
        for t in targets:
            verify_evidence_chain(t)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
