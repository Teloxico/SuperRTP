#!/usr/bin/env python3
"""
Runtime gate for the generated full-inventory packs (artifacts/generation/full-inventory/v2).

Structural checks (dimensions, formats, hashes) are done by generate_full_inventory.py
--check. This gate runs the real engines against the generated packs, using clean-room
fixtures:

  rtp-path       EasyRPG Player loads the fixtures' CharSet and ChipSet from the pack given
                 with --rtp-path: the log shows the map loaded and no "Image not found",
                 and the screen has no missing-asset banner.
  installed      The pack is packaged as its release archive (tools/release/package_release.py),
                 extracted, and installed with its own install.py; EasyRPG then runs with no
                 RTP option and must find the pack by itself:
                   xdg              default install to $XDG_DATA_HOME/rtp/<2000|2003>
                   wine-user        --wine-prefix: HKCU registry value in a Wine prefix
                   wine-machine     --wine-prefix --register machine: HKLM (32-bit view)
                 Afterwards install.py --uninstall must remove the files and registry values.
  character      mkxp-z runs the XP/VX/VX Ace character fixtures against the pack: Bitmap.new
                 of the slot resolves through the RTP with the pack file's dimensions.
  scan           Every image of the XP/VX/VX Ace packs, loaded by mkxp-z through the RTP list
                 that install.py --mkxp-json wrote. Every size must match the manifest; a
                 contact sheet of sampled images is captured for inspection.
  wolf           Game.exe (Wine) draws one generated CharaChip in the WOLF fixture: every
                 event cell matches the sheet pixel for pixel and the engine reports 72x128.
                 WOLF has no RTP lookup, so this checks the image, not an installation.

    python3 tools/verify_generated_packs.py          # writes runtime-gate.json + screenshots

The report binds each loaded file's SHA-256 and the engine versions.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import easyrpg_runtime as easyrpg
import mkxp_runtime as mkxp
import verify_rmvx_runtime as rmvx
import verify_rmxp_runtime as rmxp
import verify_wolf_runtime as wolf_verify
import wolf_runtime as wolf
from png_utils import decode_png_rgb, read_png
from release import package_release
from repo import REPO_ROOT, evidence_timestamp, load_json, repo_path, sha256_file, write_json

GATE_ROOT = repo_path("artifacts", "generation", "full-inventory", "v2")
PACKS = os.path.join(GATE_ROOT, "packs")
SCREEN_DIR = os.path.join(GATE_ROOT, "runtime-gate")
SCAN_FIXTURE = repo_path("tests", "fixtures", "rgss_pack_scan", "fixture.rb")
MIN_SESSION_S = 6.0   # EasyRPG shows its built-in logo first; the map is loaded well within this
SCAN_THUMBNAILS = 48
SCAN_RECORD_SECONDS = 30

EASYRPG_CASES = [
    # (pack, engine target, fixture, name the fixture requests, pack file it resolves to). The
    # fixtures request legacy alias names; EasyRPG maps them to the official RTP names through
    # its rtp_table, the same mapping as registry/slots/<target>.json (docs/engine-facts.md).
    ("rm2000-en", "rm2000", "rm2000_min", "CharSet/Actor1", "CharSet/Actor1.png"),
    ("rm2000-en", "rm2000", "rm2000_chipset_min", "ChipSet/Basis", "ChipSet/World.png"),
    ("rm2003-en", "rm2003", "rm2003_min", "CharSet/Hero1", "CharSet/Actor1.png"),
    ("rm2003-en", "rm2003", "rm2003_chipset_min", "ChipSet/Main", "ChipSet/World.png"),
]
INSTALLED_CASES = [
    # (pack, engine target, fixture, requested, resolved file, install mode)
    ("rm2000-en", "rm2000", "rm2000_min", "CharSet/Actor1", "CharSet/Actor1.png", "xdg"),
    ("rm2003-en", "rm2003", "rm2003_min", "CharSet/Hero1", "CharSet/Actor1.png", "xdg"),
    ("rm2000-en", "rm2000", "rm2000_min", "CharSet/Actor1", "CharSet/Actor1.png", "wine-user"),
    ("rm2003-en", "rm2003", "rm2003_min", "CharSet/Hero1", "CharSet/Actor1.png", "wine-machine"),
]
MKXP_CASES = [
    # (pack, rgss version, fixture, slot, marker)
    ("rmxp", 1, "rmxp_character_min", "Graphics/Characters/001-Fighter01.png", "SUPERRTP_RMXP_CHARACTER_LOADED"),
    ("rmvx", 2, "rmvx_character_min", "Graphics/Characters/Actor1.png", "SUPERRTP_RMVX_CHARACTER_LOADED"),
    ("rmvxace", 3, "rmvxace_character_min", "Graphics/Characters/Actor1.png", "SUPERRTP_RMVXACE_CHARACTER_LOADED"),
]
SCAN_CASES = [("rmxp", 1), ("rmvx", 2), ("rmvxace", 3)]
BITMAP_EXTENSIONS = (".png", ".jpg")


def _slot_sha(pack: str, slot: str) -> str:
    path = os.path.join(PACKS, pack, slot)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Generated pack {pack} lacks {slot}")
    return sha256_file(path)


def _manifest_entries(pack: str) -> list:
    return [e for e in load_json(os.path.join(GATE_ROOT, "manifest.json"))["entries"] if e["pack"] == pack]


# ---------------------------------------------------------------------------
# Release archive -> install.py
# ---------------------------------------------------------------------------

def extract_release(pack: str, workdir: str) -> str:
    """Builds the pack's release archive, extracts it, and returns the folder holding install.py."""
    manifest_sha = sha256_file(os.path.join(GATE_ROOT, "manifest.json"))
    os.makedirs(workdir, exist_ok=True)
    archive = package_release.build_archive(pack, _manifest_entries(pack), GATE_ROOT, manifest_sha,
                                            package_release.read_version(), workdir)
    with zipfile.ZipFile(archive) as z:
        z.extractall(workdir)
    return os.path.join(workdir, f"SuperRTP-{pack}")


def run_installer(release_dir: str, args: list, env: dict) -> str:
    result = subprocess.run([sys.executable, os.path.join(release_dir, "install.py"), *args],
                            env=env, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise ValueError(f"install.py {' '.join(args)} failed: {(result.stdout + result.stderr).strip()[-800:]}")
    return result.stdout


def isolated_env(home: str, **extra) -> dict:
    """HOME and XDG paths inside `home`, so neither the user's RTPs nor ~/.wine are seen."""
    env = dict(os.environ, HOME=home, XDG_DATA_HOME=os.path.join(home, "xdg"),
               XDG_DATA_DIRS=os.path.join(home, "no-system-data"))
    env.pop("WINEPREFIX", None)
    # Installer and Wine helper runs get no display, so nothing can appear on the user's screen;
    # engine sessions get their private Xvfb display from easyrpg_runtime.session.
    for key in ("DISPLAY", "WAYLAND_DISPLAY"):
        env.pop(key, None)
    for key in ("RPG_RTP_PATH", "RPG2K_RTP_PATH", "RPG2K3_RTP_PATH"):
        env.pop(key, None)
    env.update(extra)
    return env


def prepare_wine_prefix(wine: str, prefix: str, env: dict) -> None:
    """Creates a Wine prefix. The first start of the portable Wine build in a new prefix can
    fail before the prefix exists (docs/known-issues.md), so one retry is allowed."""
    for attempt in (1, 2):
        result = subprocess.run([wine, "wineboot", "--init"], env=dict(env, WINEPREFIX=prefix, WINEDEBUG="-all"),
                                capture_output=True, text=True, timeout=600)
        if result.returncode == 0 and os.path.isfile(os.path.join(prefix, "system.reg")):
            return
    raise RuntimeError(f"wineboot failed: {result.stderr.strip()[-800:]}")


def registry_mentions(prefix: str, path: str) -> bool:
    """Whether the prefix's registry files hold `path` as a registered value."""
    needle = ("z:" + os.path.abspath(path)).replace("/", "\\\\").lower()   # .reg files escape each backslash
    for reg_file in ("user.reg", "system.reg"):
        with open(os.path.join(prefix, reg_file), encoding="utf-8", errors="replace") as f:
            if needle in f.read().lower():
                return True
    return False


def wait_for_registry(prefix: str, path: str, present: bool, timeout: float = 60.0) -> None:
    """Wine's server saves registry changes to user.reg/system.reg shortly after its last
    client exits; EasyRPG reads those files, so wait until the change is on disk."""
    deadline = time.monotonic() + timeout
    while registry_mentions(prefix, path) != present:
        if time.monotonic() > deadline:
            raise TimeoutError(f"Wine registry in {prefix} still {'lacks' if present else 'holds'} {path} after {timeout:.0f}s")
        time.sleep(1)


# ---------------------------------------------------------------------------
# EasyRPG
# ---------------------------------------------------------------------------

def _easyrpg_session(player, version, pack, target, fixture, requested, slot, name, rtp_dir=None, env=None):
    shot = os.path.join(SCREEN_DIR, f"{name}.png")
    with tempfile.TemporaryDirectory(prefix="superrtp_gate_") as tmp:
        log = os.path.join(tmp, "session.log")
        cmd = easyrpg.player_command(player, repo_path("tests", "fixtures", fixture), easyrpg.ENGINE_MODES[target],
                                     rtp_dir=rtp_dir, log_file=log, discover_rtp=rtp_dir is None)
        started = time.monotonic()

        def ready(png):
            if time.monotonic() - started < MIN_SESSION_S:
                return False
            _, _, pixels = decode_png_rgb(png)
            if easyrpg.warning_text_pixels(pixels):
                raise ValueError("EasyRPG shows its missing-asset warning banner")
            # The fixture maps fill the screen; a mostly black frame means nothing was drawn
            # (still starting, or the session is not on this display).
            drawn = sum(1 for row in pixels for px in row if px != (0, 0, 0))
            if drawn < 0.9 * len(pixels) * len(pixels[0]):
                raise ValueError(f"Only {drawn} drawn pixels: the fixture map is not on screen")
            return True

        with easyrpg.session(cmd, log_file=log, env=env) as display:
            easyrpg.wait_for(display, ready, shot, timeout=40)
        text = open(log, encoding="utf-8", errors="replace").read()
    missing = re.findall(r"Image not found: ([^\r\n]+)", text)
    if missing:
        raise ValueError(f"{name}: EasyRPG could not find {missing}")
    if "Loaded Map" not in text:
        raise ValueError(f"{name}: the fixture map was never loaded")
    return {"engine": version, "fixture": fixture, "pack": pack, "requested": requested, "slot": slot,
            "slot_sha256": _slot_sha(pack, slot), "rtp_paths": re.findall(r"Adding (\S+) to RTP path", text),
            "screenshot": os.path.relpath(shot, GATE_ROOT), "screenshot_sha256": sha256_file(shot), "status": "LOADED"}


def run_easyrpg(player, version, pack, target, fixture, requested, slot) -> dict:
    result = _easyrpg_session(player, version, pack, target, fixture, requested, slot, f"{fixture}__{pack}",
                              rtp_dir=os.path.join(PACKS, pack))
    result.pop("rtp_paths")
    return dict(result, case="rtp-path")


def run_installed(player, version, wine, pack, target, fixture, requested, slot, mode) -> dict:
    """Release archive -> install.py (mode) -> EasyRPG finds the RTP with no RTP option -> uninstall."""
    with tempfile.TemporaryDirectory(prefix="superrtp_install_") as tmp:
        release = extract_release(pack, os.path.join(tmp, "release"))
        home = os.path.join(tmp, "home")
        os.makedirs(home)
        env = isolated_env(home)
        if mode == "xdg":
            args, expected_dir = [], os.path.join(env["XDG_DATA_HOME"], "rtp", target[2:])
        else:
            prefix = os.path.join(home, "wineprefix")
            # The portable Wine launcher finds itself under $HOME; WINEPREFIX and XDG_DATA_HOME
            # still keep the user's own prefix and RTPs out of the run.
            env["HOME"] = os.environ["HOME"]
            env["PATH"] = os.path.dirname(wine) + os.pathsep + env["PATH"]
            prepare_wine_prefix(wine, prefix, env)
            expected_dir = os.path.join(tmp, "installed")
            args = ["--dest", expected_dir, "--wine-prefix", prefix]
            if mode == "wine-machine":
                args += ["--register", "machine"]
        installed = run_installer(release, args, env)
        if mode != "xdg":
            wait_for_registry(prefix, expected_dir, present=True)
            env["WINEPREFIX"] = prefix
        result = _easyrpg_session(player, version, pack, target, fixture, requested, slot,
                                  f"{fixture}__{pack}__installed-{mode}", env=env)
        found = [p for p in result["rtp_paths"] if os.path.realpath(p) == os.path.realpath(expected_dir)]
        if not found:
            raise ValueError(f"EasyRPG did not add the installed pack {expected_dir} to its RTP path: {result['rtp_paths']}")
        run_installer(release, ["--uninstall"], env)
        leftovers = [os.path.join(d, f) for d, _, fs in os.walk(expected_dir) for f in fs] if os.path.exists(expected_dir) else []
        if leftovers:
            raise ValueError(f"--uninstall left {len(leftovers)} files, e.g. {leftovers[0]}")
        if mode != "xdg":
            wait_for_registry(prefix, expected_dir, present=False)
    result.pop("rtp_paths")
    return dict(result, case=f"installed-{mode}", installer_output=installed.strip().splitlines(), uninstalled=True)


# ---------------------------------------------------------------------------
# mkxp-z
# ---------------------------------------------------------------------------

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
    result = {"case": "character", "engine": f"mkxp-z {mkxp.PINNED_MKXP_COMMIT[:7]}", "fixture": fixture, "pack": pack,
              "slot": slot, "slot_sha256": _slot_sha(pack, slot), "loaded_size": [image.width, image.height],
              "fixture_exit": run.exit_code, "status": "LOADED"}
    if run.exit_code == 0:
        result.update(screenshot=os.path.relpath(shot, GATE_ROOT), screenshot_sha256=sha256_file(shot))
    return result


def _contact_sheet_drawn(width: int, height: int):
    """True once the scan's contact sheet with its four magenta corner markers is on screen."""
    def drawn(rgb: bytes) -> bool:
        for x, y in ((1, 1), (width - 2, 1), (1, height - 2), (width - 2, height - 2)):
            o = (y * width + x) * 3
            if tuple(rgb[o:o + 3]) != (255, 0, 255):
                return False
        return True
    return drawn


def run_scan(mkxp_bin: str, pack: str, rgss: int) -> dict:
    """Loads every image of the pack in mkxp-z through the RTP list install.py wrote."""
    entries = sorted((e for e in _manifest_entries(pack) if e["extension"] in BITMAP_EXTENSIONS and e["path"].startswith("Graphics/")),
                     key=lambda e: e["path"])
    expected = {os.path.splitext(e["path"])[0]: (e["details"]["width"], e["details"]["height"]) for e in entries}
    if len(expected) != len(entries):
        raise ValueError(f"{pack}: two images share a name without extension; RGSS lookups would be ambiguous")
    step = max(1, len(entries) // SCAN_THUMBNAILS)
    thumbs = {os.path.splitext(e["path"])[0] for e in entries[::step][:SCAN_THUMBNAILS]}
    width, height = mkxp.SCREEN_SIZES[rgss]
    name = f"rgss_pack_scan__{pack}"
    shot = os.path.join(SCREEN_DIR, f"{name}.png")
    with tempfile.TemporaryDirectory(prefix="superrtp_scan_") as tmp:
        release = extract_release(pack, os.path.join(tmp, "release"))
        home = os.path.join(tmp, "home")
        os.makedirs(home)
        user_conf = os.path.join(tmp, "user-mkxp.json")
        run_installer(release, ["--mkxp-json", user_conf], isolated_env(home))
        rtp = load_json(user_conf)["RTP"]
        game = os.path.join(tmp, "game")
        os.makedirs(game)
        shutil.copyfile(SCAN_FIXTURE, os.path.join(game, "fixture.rb"))
        with open(os.path.join(game, "scan_list.txt"), "w", encoding="utf-8") as f:
            f.write(f"{width} {height}\n" + "".join(("*" if p in thumbs else "") + p + "\n" for p in expected))
        conf = mkxp.portable_config(rgss, game, rtp)
        run = mkxp.run_session(mkxp_bin, conf, shot, SCAN_RECORD_SECONDS, _contact_sheet_drawn(width, height), timeout=180)
    errors = re.findall(r"SUPERRTP_SCAN_ERROR ([^\n]+)", run.stderr)
    loaded = {m.group(1): (int(m.group(2)), int(m.group(3)))
              for m in re.finditer(r"SUPERRTP_SCAN (\S.*?) (\d+)x(\d+)$", run.stderr, re.MULTILINE)}
    if run.exit_code != 0 or errors or "SUPERRTP_SCAN_DONE" not in run.stderr:
        raise ValueError(f"{name}: exit {run.exit_code}, {len(errors)} load errors, e.g. {errors[:3]}; {run.stderr.strip()[-400:]}")
    wrong = {p: (loaded.get(p), size) for p, size in expected.items() if loaded.get(p) != size}
    if wrong:
        raise ValueError(f"{name}: {len(wrong)} images missing or with wrong size, e.g. {list(wrong.items())[:3]}")
    return {"case": "scan", "engine": f"mkxp-z {mkxp.PINNED_MKXP_COMMIT[:7]}", "pack": pack, "rgss_version": rgss,
            "images_loaded": len(loaded), "all_sizes_match_manifest": True, "rtp_from": "install.py --mkxp-json",
            "screenshot": os.path.relpath(shot, GATE_ROOT), "screenshot_sha256": sha256_file(shot), "status": "LOADED"}


# ---------------------------------------------------------------------------
# WOLF
# ---------------------------------------------------------------------------

def run_wolf(game_exe: str, wine: str) -> dict:
    entries = sorted((e for e in _manifest_entries("wolf") if e["path"].startswith("Data/CharaChip/")),
                     key=lambda e: e["path"])
    if not entries:
        raise FileNotFoundError("The WOLF pack has no CharaChip images")
    slot = entries[0]["path"]
    char = os.path.join(PACKS, "wolf", slot)
    shot = os.path.join(SCREEN_DIR, "wolf_character_min__wolf.png")
    wolf.prepare_wine_prefix(wine)
    session = wolf.run_session(repo_path("tests", "fixtures", "wolf_character_min"), game_exe, wine, shot,
                               lambda path: bool(wolf_verify.verify_charachip_composite(path, char)), charachip_png=char)
    if session.error_log:
        raise ValueError(f"WOLF wrote an error log: {session.error_log[:300]!r}")
    lookup = wolf_verify.verify_charachip_composite(shot, char)
    return {"case": "wolf", "engine": f"WOLF RPG Editor {wolf.PINNED_WOLF_VERSION} Game.exe, {wolf.wine_version(wine)}",
            "fixture": "wolf_character_min", "pack": "wolf", "slot": slot, "slot_sha256": sha256_file(char),
            "engine_reported_size": lookup, "cells_verified": len(wolf_verify.COMPOSITE_SLOTS),
            "screenshot": os.path.relpath(shot, GATE_ROOT), "screenshot_sha256": sha256_file(shot), "status": "LOADED"}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--only", choices=("rtp-path", "installed", "character", "scan", "wolf"), action="append",
                        help="run only these cases (the report then lists only them)")
    args = parser.parse_args()
    if not os.path.isfile(os.path.join(GATE_ROOT, "manifest.json")):
        sys.exit("Generated packs not found; run tools/asset_generation/generate_full_inventory.py --write first")
    selected = set(args.only or ("rtp-path", "installed", "character", "scan", "wolf"))
    os.makedirs(SCREEN_DIR, exist_ok=True)
    player = easyrpg.find_player()
    version = easyrpg.player_version(player)
    easyrpg.check_pinned_version(version)
    mkxp_bin = mkxp.find_mkxp()
    mkxp.read_build_metadata(mkxp_bin)
    wine = wolf.find_wine()

    cases = []
    if "rtp-path" in selected:
        cases += [(f"{c[2]}__{c[0]}", run_easyrpg, (player, version, *c)) for c in EASYRPG_CASES]
    if "installed" in selected:
        cases += [(f"{c[2]}__{c[0]}__installed-{c[5]}", run_installed, (player, version, wine, *c)) for c in INSTALLED_CASES]
    if "character" in selected:
        cases += [(f"{c[2]}__{c[0]}", run_mkxp, (mkxp_bin, *c)) for c in MKXP_CASES]
    if "scan" in selected:
        cases += [(f"rgss_pack_scan__{c[0]}", run_scan, (mkxp_bin, *c)) for c in SCAN_CASES]
    if "wolf" in selected:
        cases += [("wolf_character_min__wolf", run_wolf, (wolf.find_game_exe(), wine))]

    results, failures = [], []
    for name, run, case_args in cases:
        try:
            results.append(run(*case_args))
            print(f"[LOADED] {name}", flush=True)
        except (ValueError, FileNotFoundError, TimeoutError, RuntimeError) as exc:
            failures.append(f"{name}: {exc}")
            print(f"[FAILED] {name}: {exc}", flush=True)
    report = {"recorded_at": evidence_timestamp(), "manifest_sha256": sha256_file(os.path.join(GATE_ROOT, "manifest.json")),
              "cases_run": sorted(selected), "results": results, "failures": failures}
    write_json(os.path.join(GATE_ROOT, "runtime-gate.json"), report)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
