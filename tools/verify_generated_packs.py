#!/usr/bin/env python3
"""
Runtime gate for the generated full-inventory packs (artifacts/generation/full-inventory/v2).

Structural checks (dimensions, formats, hashes) are done by generate_full_inventory.py
--check. This gate runs the real engines against the generated packs, using the existing
clean-room fixtures with the RTP pointed at a pack:

  rm2000-en, rm2003-en   EasyRPG Player loads the fixture's CharSet (rm*_min) and ChipSet
                         (rm*_chipset_min) from the pack: the session log shows the map
                         loaded and no "Image not found", and the screen has no EasyRPG
                         missing-asset banner.
  rmxp, rmvx, rmvxace    mkxp-z runs the character fixture: Bitmap.new of the slot resolves
                         through the pack (SUPERRTP_*_CHARACTER_LOADED with the pack file's
                         dimensions) and the script exits 0.

WOLF has no RTP search path (files resolve relative to the game), so its packs are
covered by the structural checks only.

    python3 tools/verify_generated_packs.py          # writes runtime-gate.json + screenshots

The report binds each loaded slot's SHA-256 and the engine versions.
"""

import argparse
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import easyrpg_runtime as easyrpg
import mkxp_runtime as mkxp
import verify_rmvx_runtime as rmvx
import verify_rmxp_runtime as rmxp
from png_utils import decode_png_rgb, read_png
from repo import REPO_ROOT, evidence_timestamp, repo_path, sha256_file, write_json

GATE_ROOT = repo_path("artifacts", "generation", "full-inventory", "v2")
PACKS = os.path.join(GATE_ROOT, "packs")
SCREEN_DIR = os.path.join(GATE_ROOT, "runtime-gate")
MIN_SESSION_S = 6.0   # EasyRPG shows its built-in logo first; the map is loaded well within this

EASYRPG_CASES = [
    # (pack, engine target, fixture, name the fixture requests, pack file it resolves to). The
    # fixtures request legacy alias names; EasyRPG maps them to the official RTP names through
    # its rtp_table, the same mapping as registry/slots/<target>.json (docs/engine-facts.md).
    ("rm2000-en", "rm2000", "rm2000_min", "CharSet/Actor1", "CharSet/Actor1.png"),
    ("rm2000-en", "rm2000", "rm2000_chipset_min", "ChipSet/Basis", "ChipSet/World.png"),
    ("rm2003-en", "rm2003", "rm2003_min", "CharSet/Hero1", "CharSet/Actor1.png"),
    ("rm2003-en", "rm2003", "rm2003_chipset_min", "ChipSet/Main", "ChipSet/World.png"),
]
MKXP_CASES = [
    # (pack, rgss version, fixture, slot, marker)
    ("rmxp", 1, "rmxp_character_min", "Graphics/Characters/001-Fighter01.png", "SUPERRTP_RMXP_CHARACTER_LOADED"),
    ("rmvx", 2, "rmvx_character_min", "Graphics/Characters/Actor1.png", "SUPERRTP_RMVX_CHARACTER_LOADED"),
    ("rmvxace", 3, "rmvxace_character_min", "Graphics/Characters/Actor1.png", "SUPERRTP_RMVXACE_CHARACTER_LOADED"),
]


def _slot_sha(pack: str, slot: str) -> str:
    path = os.path.join(PACKS, pack, slot)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Generated pack {pack} lacks {slot}")
    return sha256_file(path)


def run_easyrpg(player: str, version: str, pack: str, target: str, fixture: str, requested: str, slot: str) -> dict:
    import time
    name = f"{fixture}__{pack}"
    shot = os.path.join(SCREEN_DIR, f"{name}.png")
    with tempfile.TemporaryDirectory(prefix="superrtp_gate_") as tmp:
        log = os.path.join(tmp, "session.log")
        cmd = easyrpg.player_command(player, repo_path("tests", "fixtures", fixture), easyrpg.ENGINE_MODES[target],
                                     rtp_dir=os.path.join(PACKS, pack), log_file=log)
        started = time.monotonic()

        def ready(png):
            if time.monotonic() - started < MIN_SESSION_S:
                return False
            _, _, pixels = decode_png_rgb(png)
            if easyrpg.warning_text_pixels(pixels):
                raise ValueError("EasyRPG shows its missing-asset warning banner")
            return True

        with easyrpg.session(cmd, log_file=log) as display:
            easyrpg.wait_for(display, ready, shot, timeout=40)
        text = open(log, encoding="utf-8", errors="replace").read()
    missing = re.findall(r"Image not found: ([^\r\n]+)", text)
    if missing:
        raise ValueError(f"{name}: EasyRPG could not find {missing}")
    if "Loaded Map" not in text:
        raise ValueError(f"{name}: the fixture map was never loaded")
    return {"engine": version, "fixture": fixture, "pack": pack, "requested": requested, "slot": slot,
            "slot_sha256": _slot_sha(pack, slot),
            "screenshot": os.path.relpath(shot, GATE_ROOT), "screenshot_sha256": sha256_file(shot), "status": "LOADED"}


def run_mkxp(mkxp_bin: str, pack: str, rgss: int, fixture: str, slot: str, marker: str) -> dict:
    name = f"{fixture}__{pack}"
    shot = os.path.join(SCREEN_DIR, f"{name}.png")
    rel_pack = os.path.relpath(os.path.join(PACKS, pack), REPO_ROOT)
    conf = mkxp.portable_config(rgss, f"tests/fixtures/{fixture}", [rel_pack])
    scene = rmxp.scene_drawn if rgss == 1 else rmvx.scene_drawn
    # The VX/VX Ace fixtures stop with exit 4 after loading when the sheet is not the 288x256
    # calibration size; real VX sheets use 32x32 frames (384x256), so that exit is expected here
    # and only accepted when the loaded size equals the pack file's.
    calibration_size_exit = 4 if rgss in (2, 3) else None
    run = mkxp.run_session(mkxp_bin, conf, shot, mkxp.POSITIVE_RECORD_SECONDS, lambda f: scene(f, False),
                           require_frame=calibration_size_exit is None)
    # Process.exit! in the fixture skips flushing stdout, so on the calibration-size exit the
    # loaded size is read from the fixture's unbuffered stderr line ("... got WxH").
    loaded = (re.search(re.escape(marker) + r" (\d+)x(\d+)", run.stdout)
              or re.search(r"SUPERRTP_RMVX(?:ACE)?_DIMENSION_ERROR: Expected 288x256, got (\d+)x(\d+)", run.stderr))
    if not loaded or run.exit_code not in (0, calibration_size_exit):
        raise ValueError(f"{name}: mkxp-z exit {run.exit_code}, output: {run.log.strip()[-600:]}")
    image = read_png(os.path.join(PACKS, pack, slot))
    if (int(loaded.group(1)), int(loaded.group(2))) != (image.width, image.height):
        raise ValueError(f"{name}: mkxp-z loaded {loaded.group(1)}x{loaded.group(2)}, pack file is {image.width}x{image.height}")
    # The build is verified against the pin in main(); the version line on stdout is lost when the
    # fixture exits with Process.exit!.
    result = {"engine": f"mkxp-z {mkxp.PINNED_MKXP_COMMIT[:7]}", "fixture": fixture, "pack": pack, "slot": slot,
              "slot_sha256": _slot_sha(pack, slot), "loaded_size": [image.width, image.height],
              "fixture_exit": run.exit_code, "status": "LOADED"}
    if run.exit_code == 0:
        result.update(screenshot=os.path.relpath(shot, GATE_ROOT), screenshot_sha256=sha256_file(shot))
    return result


def main():
    argparse.ArgumentParser(description=__doc__.split("\n")[1]).parse_args()
    if not os.path.isfile(os.path.join(GATE_ROOT, "manifest.json")):
        sys.exit("Generated packs not found; run tools/asset_generation/generate_full_inventory.py --write first")
    os.makedirs(SCREEN_DIR, exist_ok=True)
    player = easyrpg.find_player()
    version = easyrpg.player_version(player)
    easyrpg.check_pinned_version(version)
    mkxp_bin = mkxp.find_mkxp()
    mkxp.read_build_metadata(mkxp_bin)
    results, failures = [], []
    for case in EASYRPG_CASES:
        try:
            results.append(run_easyrpg(player, version, *case))
        except (ValueError, FileNotFoundError, TimeoutError) as exc:
            failures.append(f"{case[2]}__{case[0]}: {exc}")
    for case in MKXP_CASES:
        try:
            results.append(run_mkxp(mkxp_bin, *case))
        except (ValueError, FileNotFoundError, TimeoutError) as exc:
            failures.append(f"{case[2]}__{case[0]}: {exc}")
    report = {"recorded_at": evidence_timestamp(), "manifest_sha256": sha256_file(os.path.join(GATE_ROOT, "manifest.json")),
              "results": results, "failures": failures,
              "not_runtime_checked": {"wolf": "no RTP search path; covered by structural checks"}}
    write_json(os.path.join(GATE_ROOT, "runtime-gate.json"), report)
    for r in results:
        print(f"[LOADED] {r['pack']}: {r['slot']} via {r['fixture']} ({r['engine']})")
    for f in failures:
        print(f"[FAILED] {f}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
