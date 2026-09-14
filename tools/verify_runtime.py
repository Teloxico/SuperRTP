#!/usr/bin/env python3
"""
SuperRTP Deterministic Runtime & Visual Verification Tool.

Verifies and reproduces EasyRPG Player runtime execution:
  - Executes EasyRPG with --replay-input tests/fixtures/rm2000_min/replay_turn_directions.input
  - Captures and verifies directional character frames (Down, Left, Up, Right)
  - Captures and verifies isolated missing-asset fallback (negative control)
  - Links runtime screenshots to target manifest hashes, fixture hashes, and replay hashes
  - Writes/validates artifacts/runtime/rm2000/charset/verification_evidence.json

Usage:
  python3 tools/verify_runtime.py --verify           # Check evidence chain and screenshot assertions
  python3 tools/verify_runtime.py --run-replay       # Live execution in EasyRPG to reproduce screenshots
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
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def get_evidence_timestamp():
    sde = os.environ.get("SOURCE_DATE_EPOCH")
    if sde:
        try:
            return datetime.fromtimestamp(int(sde), tz=timezone.utc).isoformat()
        except ValueError:
            pass
    return datetime.now(timezone.utc).isoformat()
ARTIFACTS_DIR = os.path.join(REPO_ROOT, "artifacts", "runtime", "rm2000", "charset")
EVIDENCE_PATH = os.path.join(ARTIFACTS_DIR, "verification_evidence.json")
FIXTURE_DIR = os.path.join(REPO_ROOT, "tests", "fixtures", "rm2000_min")
TARGET_DIR = os.path.join(REPO_ROOT, "generated", "rm2000")
REPLAY_PATH = os.path.join(FIXTURE_DIR, "replay_turn_directions.input")

def compute_sha256(filepath):
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def decode_png_rgb(filepath):
    """
    Decodes a standard 24-bit PNG file into width, height, and a 2D list of (R, G, B) tuples,
    implementing standard PNG unfiltering (None, Sub, Up, Average, Paeth) per RFC 2083.
    """
    with open(filepath, "rb") as f:
        data = f.read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"Not a valid PNG file: {filepath}")

    w, h = struct.unpack(">II", data[16:24])
    pos = 8
    idat = bytearray()
    while pos < len(data):
        length = struct.unpack(">I", data[pos:pos+4])[0]
        ctype = data[pos+4:pos+8]
        if ctype == b"IDAT":
            idat.extend(data[pos+8:pos+8+length])
        pos += 12 + length

    raw = bytearray(zlib.decompress(bytes(idat)))
    bpp = 3  # Standard 24-bit RGB
    stride = 1 + w * bpp
    recon = bytearray(w * h * bpp)
    prior = bytearray(w * bpp)

    for y in range(h):
        filter_type = raw[y * stride]
        filt = raw[y * stride + 1 : (y + 1) * stride]
        line = bytearray(w * bpp)

        if filter_type == 0:  # None
            line[:] = filt
        elif filter_type == 1:  # Sub
            for x in range(w * bpp):
                a = line[x - bpp] if x >= bpp else 0
                line[x] = (filt[x] + a) & 0xff
        elif filter_type == 2:  # Up
            for x in range(w * bpp):
                line[x] = (filt[x] + prior[x]) & 0xff
        elif filter_type == 3:  # Average
            for x in range(w * bpp):
                a = line[x - bpp] if x >= bpp else 0
                line[x] = (filt[x] + ((a + prior[x]) >> 1)) & 0xff
        elif filter_type == 4:  # Paeth
            for x in range(w * bpp):
                a = line[x - bpp] if x >= bpp else 0
                b = prior[x]
                c = prior[x - bpp] if x >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (filt[x] + pr) & 0xff
        else:
            raise ValueError(f"Unknown PNG filter type {filter_type}")

        prior[:] = line
        recon[y * w * bpp : (y + 1) * w * bpp] = line

    pixels = []
    for y in range(h):
        row = [(recon[y*w*3 + x*3], recon[y*w*3 + x*3 + 1], recon[y*w*3 + x*3 + 2]) for x in range(w)]
        pixels.append(row)
    return w, h, pixels

def verify_directional_screenshot(filepath, expected_direction, target=None):
    """
    Mechanically inspects screenshot pixels to verify directional visual correctness:
    1. Centroid world position.
    2. Character arrow shape orientation (tip vs wings) to prevent row-order inversion bugs.
    """
    if target is None:
        target = "rm2003" if "rm2003" in filepath else "rm2000"

    w, h, pixels = decode_png_rgb(filepath)
    if (w, h) != (640, 480):
        raise ValueError(f"Unexpected image dimensions {w}x{h} in {filepath}, expected 640x480")

    if expected_direction == "negative_control":
        # Check for non-black text pixels at top-left
        text_pixels = [
            (x, y) for y in range(5, 30) for x in range(5, 250)
            if pixels[y][x] != (0, 0, 0)
        ]
        if len(text_pixels) < 50:
            raise ValueError(f"Negative control missing error text at top-left: found {len(text_pixels)} pixels")
        # Check center checkerboard placeholder
        center_colors = {
            pixels[y][x] for y in range(180, 260) for x in range(300, 340)
            if pixels[y][x] != (0, 0, 0)
        }
        if len(center_colors) < 2:
            raise ValueError(f"Negative control missing missing-asset placeholder in center")
        return {"status": "VERIFIED", "error_text_pixels": len(text_pixels)}

    # For directional character states: find character cyan body and gold accent pixels
    # Cyan body: R < 50, G > 180, B > 180
    # Gold accent: R > 200, G > 180, B < 100
    cyans = [
        (x, y) for y in range(160, 260) for x in range(270, 370)
        if pixels[y][x][0] < 50 and pixels[y][x][1] > 180 and pixels[y][x][2] > 180
    ]
    yellows = [
        (x, y) for y in range(160, 260) for x in range(270, 370)
        if pixels[y][x][0] > 200 and pixels[y][x][1] > 180 and pixels[y][x][2] < 100
    ]

    if len(cyans) < 30 or len(yellows) < 10:
        raise ValueError(f"Character sprite not found in expected center region for {filepath} (cyans={len(cyans)}, yellows={len(yellows)})")

    # 1. Screen-space centroid verification
    c_x = sum(x for x, y in cyans) / len(cyans)
    c_y = sum(y for x, y in cyans) / len(cyans)

    expected_ranges = {
        "down":  {"x": (320, 345), "y": (210, 230)},
        "left":  {"x": (295, 315), "y": (215, 230)},
        "up":    {"x": (295, 315), "y": (180, 200)},
        "right": {"x": (325, 345), "y": (180, 200)}
    }

    exp = expected_ranges[expected_direction]
    if not (exp["x"][0] <= c_x <= exp["x"][1]) or not (exp["y"][0] <= c_y <= exp["y"][1]):
        raise ValueError(
            f"Direction position mismatch for '{expected_direction}' ({target}): center is ({c_x:.1f}, {c_y:.1f}), "
            f"expected x in {exp['x']}, y in {exp['y']}"
        )

    # 2. Sprite shape orientation verification (arrow geometry inspection)
    min_x = min(x for x, y in cyans)
    max_x = max(x for x, y in cyans)
    min_y = min(y for x, y in cyans)
    max_y = max(y for x, y in cyans)

    top_span_xs = [x for x, y in cyans if y <= min_y + 4]
    bot_span_xs = [x for x, y in cyans if y >= max_y - 4]
    top_w = max(top_span_xs) - min(top_span_xs) + 1
    bot_w = max(bot_span_xs) - min(bot_span_xs) + 1

    left_span_ys = [y for x, y in cyans if x <= min_x + 4]
    right_span_ys = [y for x, y in cyans if x >= max_x - 4]
    left_h = max(left_span_ys) - min(left_span_ys) + 1
    right_h = max(right_span_ys) - min(right_span_ys) + 1

    if expected_direction == "down":
        # Arrow pointing down: wide wings at top, narrow tip at bottom
        if top_w <= bot_w:
            raise ValueError(f"Sprite arrow shape mismatch: expected DOWN (top_w > bot_w), got top_w={top_w}, bot_w={bot_w}")
        if abs(left_h - right_h) > 6:
            raise ValueError(f"Sprite arrow shape asymmetry for DOWN: left_h={left_h}, right_h={right_h}")

    elif expected_direction == "up":
        # Arrow pointing up: narrow tip at top, wide wings at bottom
        if top_w >= bot_w:
            raise ValueError(f"Sprite arrow shape mismatch: expected UP (top_w < bot_w), got top_w={top_w}, bot_w={bot_w}")
        if abs(left_h - right_h) > 6:
            raise ValueError(f"Sprite arrow shape asymmetry for UP: left_h={left_h}, right_h={right_h}")

    elif expected_direction == "left":
        # Arrow pointing left: narrow tip at left, wide wings on right
        if left_h >= right_h:
            raise ValueError(f"Sprite arrow shape mismatch: expected LEFT (left_h < right_h), got left_h={left_h}, right_h={right_h}")

    elif expected_direction == "right":
        # Arrow pointing right: wide wings on left, narrow tip at right
        if right_h >= left_h:
            raise ValueError(f"Sprite arrow shape mismatch: expected RIGHT (right_h < left_h), got left_h={left_h}, right_h={right_h}")

    return {
        "status": "VERIFIED",
        "facing": expected_direction.upper(),
        "centroid": [round(c_x, 1), round(c_y, 1)],
        "shape_metrics": {
            "top_w": top_w, "bot_w": bot_w,
            "left_h": left_h, "right_h": right_h
        },
        "cyan_pixel_count": len(cyans),
        "accent_pixel_count": len(yellows)
    }

def get_target_config(target="rm2000"):
    artifacts_dir = os.path.join(REPO_ROOT, "artifacts", "runtime", target, "charset")
    evidence_path = os.path.join(artifacts_dir, "verification_evidence.json")
    fixture_dir = os.path.join(REPO_ROOT, "tests", "fixtures", f"{target}_min")
    target_dir = os.path.join(REPO_ROOT, "generated", target)
    replay_path = os.path.join(fixture_dir, "replay_turn_directions.input")
    engine = "rpg2k3" if target in ("rm2003", "2k3") else "rpg2k"
    return {
        "target": target,
        "engine": engine,
        "artifacts_dir": artifacts_dir,
        "evidence_path": evidence_path,
        "fixture_dir": fixture_dir,
        "target_dir": target_dir,
        "replay_path": replay_path,
    }

def verify_evidence_chain(target="rm2000"):
    """
    Verifies that the recorded verification_evidence.json matches current files, target Actor1.png, and hashes.
    """
    cfg = get_target_config(target)
    evidence_path = cfg["evidence_path"]
    target_dir = cfg["target_dir"]
    fixture_dir = cfg["fixture_dir"]
    replay_path = cfg["replay_path"]
    artifacts_dir = cfg["artifacts_dir"]

    if not os.path.exists(evidence_path):
        raise FileNotFoundError(f"Verification evidence file not found: {evidence_path}")

    with open(evidence_path, "r", encoding="utf-8") as ef:
        evidence = json.load(ef)

    print(f"=== SuperRTP Runtime Verification Evidence Check ({target}) ===")
    print(f"Target:          {evidence.get('target')}")
    print(f"Engine Mode:     {evidence.get('engine_mode')}")
    print(f"Requested Slot:  {evidence.get('requested_charset')}")
    print(f"Canonical Asset: {evidence.get('canonical_asset_id')}")
    print(f"EasyRPG Version: {evidence.get('easyrpg_version')}")
    print(f"Recorded Date:   {evidence.get('recorded_at')}")

    # Check target and engine mode
    if evidence.get("target") != target:
        raise ValueError(f"Evidence target mismatch: expected {target}, got {evidence.get('target')}")
    if evidence.get("engine_mode") != cfg["engine"]:
        raise ValueError(f"Evidence engine_mode mismatch: expected {cfg['engine']}, got {evidence.get('engine_mode')}")

    # Check requested charset
    expected_charset = "Hero1" if target == "rm2003" else "Actor1"
    if evidence.get("requested_charset") != expected_charset:
        raise ValueError(f"Evidence requested_charset mismatch: expected {expected_charset}, got {evidence.get('requested_charset')}")

    # Check canonical asset and source hash
    if evidence.get("canonical_asset_id") != "test.calibration.walking-character":
        raise ValueError(f"Unexpected canonical_asset_id: {evidence.get('canonical_asset_id')}")
    canonical_source_path = os.path.join(REPO_ROOT, "registry", "assets", "test_calibration_walking_character.rgba")
    if not os.path.exists(canonical_source_path):
        raise FileNotFoundError(f"Canonical source file missing: {canonical_source_path}")
    actual_canonical_sha256 = compute_sha256(canonical_source_path)
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

    # Check target manifest
    target_manifest = os.path.join(target_dir, "manifest.json")
    if not os.path.exists(target_manifest):
        raise FileNotFoundError(f"Target manifest not found: {target_manifest}")
    actual_target_manifest_hash = compute_sha256(target_manifest)
    if actual_target_manifest_hash != evidence["target_manifest_sha256"]:
        raise ValueError(f"Target manifest hash mismatch with evidence: expected {evidence['target_manifest_sha256']}, got {actual_target_manifest_hash}")

    # Check target Actor1.png binary against evidence
    target_actor1 = os.path.join(target_dir, "CharSet", "Actor1.png")
    if not os.path.exists(target_actor1):
        raise FileNotFoundError(f"Target Actor1.png not found: {target_actor1}")
    actual_actor1_hash = compute_sha256(target_actor1)
    if actual_actor1_hash != evidence["target_actor1_sha256"]:
        raise ValueError(f"Target Actor1.png hash mismatch with evidence: expected {evidence['target_actor1_sha256']}, got {actual_actor1_hash}")

    # Check fixture manifest
    fixture_manifest = os.path.join(fixture_dir, "fixture_manifest.json")
    actual_fixture_hash = compute_sha256(fixture_manifest)
    if actual_fixture_hash != evidence["fixture_manifest_sha256"]:
        raise ValueError(f"Fixture manifest hash mismatch with evidence: expected {evidence['fixture_manifest_sha256']}, got {actual_fixture_hash}")

    # Check replay file
    actual_replay_hash = compute_sha256(replay_path)
    if actual_replay_hash != evidence["replay_input_sha256"]:
        raise ValueError(f"Replay input hash mismatch with evidence: expected {evidence['replay_input_sha256']}, got {actual_replay_hash}")

    # Check runtime logs
    pos_log = os.path.join(artifacts_dir, evidence.get("positive_runtime_log", "positive_runtime.log"))
    if not os.path.exists(pos_log):
        raise FileNotFoundError(f"Missing positive runtime log: {pos_log}")
    actual_pos_log_hash = compute_sha256(pos_log)
    if actual_pos_log_hash != evidence.get("positive_runtime_log_sha256"):
        raise ValueError(f"Positive runtime log hash mismatch: expected {evidence.get('positive_runtime_log_sha256')}, got {actual_pos_log_hash}")

    neg_log = os.path.join(artifacts_dir, evidence.get("negative_runtime_log", "negative_runtime.log"))
    if not os.path.exists(neg_log):
        raise FileNotFoundError(f"Missing negative runtime log: {neg_log}")
    actual_neg_log_hash = compute_sha256(neg_log)
    if actual_neg_log_hash != evidence.get("negative_runtime_log_sha256"):
        raise ValueError(f"Negative runtime log hash mismatch: expected {evidence.get('negative_runtime_log_sha256')}, got {actual_neg_log_hash}")

    expected_missing = f"CharSet/{expected_charset}"
    expected_diag = f"Image not found: CharSet/{expected_charset}"

    with open(neg_log, "r", encoding="utf-8", errors="replace") as nlf:
        neg_log_text = nlf.read()
    if expected_diag not in neg_log_text:
        raise ValueError(f"Expected diagnostic '{expected_diag}' not found in negative runtime log")

    # Check negative control evidence
    neg = evidence.get("negative_control")
    if not neg:
        raise ValueError("Missing negative_control in verification evidence")
    if neg.get("status") != "VERIFIED":
        raise ValueError(f"Negative control status not verified: {neg.get('status')}")
    if neg.get("expected_missing_asset") != expected_missing:
        raise ValueError(f"Negative control expected_missing_asset mismatch: expected {expected_missing}, got {neg.get('expected_missing_asset')}")
    if neg.get("diagnostic") != expected_diag:
        raise ValueError(f"Negative control diagnostic mismatch: expected '{expected_diag}', got '{neg.get('diagnostic')}'")
    neg_shot = neg.get("screenshot")
    if not neg_shot or neg_shot not in evidence.get("screenshots", {}):
        raise ValueError(f"Negative control screenshot '{neg_shot}' not recorded in screenshots")
    if neg.get("screenshot_sha256") != evidence["screenshots"][neg_shot]:
        raise ValueError("Negative control screenshot hash mismatch")

    # Check screenshots and pixel content
    for name, expected_hash in evidence["screenshots"].items():
        shot_path = os.path.join(artifacts_dir, name)
        if not os.path.exists(shot_path):
            raise FileNotFoundError(f"Missing screenshot: {shot_path}")
        actual_hash = compute_sha256(shot_path)
        if actual_hash != expected_hash:
            raise ValueError(f"Hash mismatch for {name}: expected {expected_hash}, got {actual_hash}")

        # Determine direction
        if "down" in name:
            dir_name = "down"
        elif "left" in name:
            dir_name = "left"
        elif "up" in name:
            dir_name = "up"
        elif "right" in name:
            dir_name = "right"
        elif "negative_control" in name:
            dir_name = "negative_control"
        else:
            dir_name = "unknown"

        result = verify_directional_screenshot(shot_path, dir_name, target=target)
        print(f"  [PASS] {name}: SHA-256 match, Visual content: {result['status']}")

    print(f"ALL RUNTIME EVIDENCE CHECKS PASSED ({target}): Evidence chain is durable and verified.")
    return True

def run_replay_and_record(target="rm2000"):
    """
    Executes EasyRPG Player with --replay-input, extracts directional frames,
    and updates verification_evidence.json for the specified target.
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
    if not os.path.exists(os.path.join(cfg["target_dir"], "CharSet", "Actor1.png")):
        from build_target import build_target
        build_target(target, output_dir=cfg["target_dir"], clean=True)

    # Get EasyRPG version
    ver_res = subprocess.run([player_bin, "--version"], capture_output=True, text=True)
    version_line = ver_res.stdout.splitlines()[0] if ver_res.stdout else "unknown"

    pos_log_path = os.path.join(cfg["artifacts_dir"], "positive_runtime.log")
    neg_log_path = os.path.join(cfg["artifacts_dir"], "negative_runtime.log")

    video_tmp = f"/tmp/easyrpg_replay_capture_{target}.mp4"
    record_cmd = (
        f"xvfb-run -s '-screen 0 640x480x24' bash -c '"
        f"ffmpeg -y -f x11grab -draw_mouse 0 -video_size 640x480 -i :99.0 -t 11 {video_tmp} & "
        f"FFMPEG_PID=$! ; sleep 0.3 ; "
        f"SDL_VIDEODRIVER=x11 {player_bin} --project-path {cfg['fixture_dir']} --rtp-path {cfg['target_dir']} "
        f"--engine {cfg['engine']} --new-game --disable-audio --no-pause-focus-lost --fullscreen "
        f"--log-file {pos_log_path} --replay-input {cfg['replay_path']} & "
        f"PLAYER_PID=$! ; wait $FFMPEG_PID ; kill $PLAYER_PID 2>/dev/null || true ; wait $PLAYER_PID 2>/dev/null || true'"
    )

    print(f"Executing EasyRPG replay for {target} under xvfb...")
    subprocess.run(record_cmd, shell=True, check=True)
    pos_log_hash = compute_sha256(pos_log_path)
    print(f"Captured positive runtime log: SHA-256 {pos_log_hash[:16]}...")

    # Extract frames:
    # 4.5s -> Down, 5.5s -> Left, 6.5s -> Up, 7.5s -> Right
    os.makedirs(cfg["artifacts_dir"], exist_ok=True)
    frames = [
        (f"{target}_charset_down.png", "00:00:04.5", "down"),
        (f"{target}_charset_left.png", "00:00:05.5", "left"),
        (f"{target}_charset_up.png", "00:00:06.5", "up"),
        (f"{target}_charset_right.png", "00:00:07.5", "right"),
    ]
    screenshot_hashes = {}
    directional_evidence = {}

    for name, ts, direction in frames:
        out_path = os.path.join(cfg["artifacts_dir"], name)
        extract_cmd = ["ffmpeg", "-y", "-ss", ts, "-i", video_tmp, "-vframes", "1", out_path]
        subprocess.run(extract_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        h = compute_sha256(out_path)
        screenshot_hashes[name] = h
        res = verify_directional_screenshot(out_path, direction, target=target)
        directional_evidence[direction] = res
        print(f"Captured {name}: SHA-256 {h[:16]}... ({res['status']})")

    # Negative control capture
    neg_filename = f"{target}_charset_negative_control.png"
    neg_path = os.path.join(cfg["artifacts_dir"], neg_filename)
    neg_cmd = (
        f"xvfb-run -s '-screen 0 640x480x24' bash -c '"
        f"SDL_VIDEODRIVER=x11 {player_bin} --project-path {cfg['fixture_dir']} --no-rtp "
        f"--engine {cfg['engine']} --new-game --disable-audio --no-pause-focus-lost --fullscreen "
        f"--log-file {neg_log_path} & "
        f"PLAYER_PID=$! ; sleep 3.5 ; "
        f"ffmpeg -y -f x11grab -draw_mouse 0 -video_size 640x480 -i :99.0 -vframes 1 {neg_path} ; "
        f"kill $PLAYER_PID 2>/dev/null || true ; wait $PLAYER_PID 2>/dev/null || true'"
    )
    subprocess.run(neg_cmd, shell=True, check=True)
    neg_hash = compute_sha256(neg_path)
    neg_log_hash = compute_sha256(neg_log_path)
    screenshot_hashes[neg_filename] = neg_hash
    neg_res = verify_directional_screenshot(neg_path, "negative_control", target=target)
    directional_evidence["negative_control"] = neg_res
    print(f"Captured negative control: SHA-256 {neg_hash[:16]}... ({neg_res['status']})")
    print(f"Captured negative runtime log: SHA-256 {neg_log_hash[:16]}...")

    # Extract diagnostic from negative runtime log
    with open(neg_log_path, "r", encoding="utf-8", errors="replace") as nlf:
        neg_log_text = nlf.read()
    diag_match = re.search(r"Image not found: ([^\r\n]+)", neg_log_text)
    if not diag_match:
        raise ValueError(f"Could not extract 'Image not found' diagnostic from negative control log: {neg_log_path}")
    extracted_diagnostic = f"Image not found: {diag_match.group(1).strip()}"

    # Clean up tmp video
    if os.path.exists(video_tmp):
        os.remove(video_tmp)

    # Build evidence dictionary
    canonical_source_path = os.path.join(REPO_ROOT, "registry", "assets", "test_calibration_walking_character.rgba")
    requested_charset = "Hero1" if target == "rm2003" else "Actor1"
    evidence = {
        "target": target,
        "engine_mode": cfg["engine"],
        "requested_charset": requested_charset,
        "canonical_asset_id": "test.calibration.walking-character",
        "canonical_source_sha256": compute_sha256(canonical_source_path),
        "target_manifest_sha256": compute_sha256(os.path.join(cfg["target_dir"], "manifest.json")),
        "target_actor1_sha256": compute_sha256(os.path.join(cfg["target_dir"], "CharSet", "Actor1.png")),
        "fixture_manifest_sha256": compute_sha256(os.path.join(cfg["fixture_dir"], "fixture_manifest.json")),
        "replay_input_sha256": compute_sha256(cfg["replay_path"]),
        "positive_runtime_log": "positive_runtime.log",
        "positive_runtime_log_sha256": pos_log_hash,
        "negative_runtime_log": "negative_runtime.log",
        "negative_runtime_log_sha256": neg_log_hash,
        "easyrpg_version": version_line,
        "recorded_at": get_evidence_timestamp(),
        "negative_control": {
            "status": neg_res["status"],
            "expected_missing_asset": f"CharSet/{requested_charset}",
            "diagnostic": extracted_diagnostic,
            "screenshot": neg_filename,
            "screenshot_sha256": neg_hash
        },
        "screenshots": screenshot_hashes,
        "directional_evidence": directional_evidence
    }

    with open(cfg["evidence_path"], "w", encoding="utf-8") as ef:
        json.dump(evidence, ef, indent=2)

    print(f"Evidence recorded in {cfg['evidence_path']}")
    return evidence

def main():
    parser = argparse.ArgumentParser(description="SuperRTP Runtime Verification Tool")
    parser.add_argument("--target", default="rm2000", choices=["rm2000", "rm2003", "all"], help="Target RTP (rm2000, rm2003, or all)")
    parser.add_argument("--verify", action="store_true", default=True, help="Verify existing evidence and screenshot assertions")
    parser.add_argument("--run-replay", action="store_true", help="Execute live EasyRPG Player replay and update evidence")
    args = parser.parse_args()

    targets = ["rm2000", "rm2003"] if args.target == "all" else [args.target]

    if args.run_replay:
        for t in targets:
            run_replay_and_record(t)
    for t in targets:
        verify_evidence_chain(t)

if __name__ == "__main__":
    main()
