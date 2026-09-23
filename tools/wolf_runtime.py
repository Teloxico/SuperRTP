#!/usr/bin/env python3
"""
WOLF RPG Editor 3.717 Game.exe driver for tools/verify_wolf_runtime.py.

Game.exe is the official 32-bit Windows runtime (PE32, i386), run under Wine inside a
private Xvfb display. Wine must be able to run 32-bit programs (WoW64 or a wine32
install). tools/install_wolf_ci.sh installs the checksum-pinned binary to
~/.local/share/wolf-3.717/Game.exe; SUPERRTP_WOLF_GAME_EXE overrides the location.

Each session runs in a throwaway copy of the fixture project, so the committed fixture
is never modified by the runtime (WOLF writes Game_ErrorLog.txt and config files next
to Game.exe).
"""

import os
import re
import shutil
import tempfile

from repo import portable_paths, repo_path, sha256_file
from runtime_harness import find_tool, managed, poll_screen, run_to_completion, spawn, x11_env, xvfb_display

PINNED_WOLF_VERSION = "3.717"
PINNED_WOLF_TAG = "v3.717"
PINNED_WOLF_COMMIT = "e733f289def676f06db8121bbdb4386cc8f634f5"  # commit of the upstream release page repository
PINNED_ARCHIVE_SHA256 = "d73c524a186eeb9e4b6c4b6e2350c3f2449c05ce9a94b3edeebeff18c3ec842d"
PINNED_GAME_EXE_SHA256 = "91821bd2439f562811060904498086709b8ac603640551e4f2fca45a0ff5f999"
DEFAULT_GAME_EXE = "~/.local/share/wolf-3.717/Game.exe"

SCREEN_W, SCREEN_H = 640, 480
READY_TIMEOUT_S = 30.0
POLL_INTERVAL_S = 0.5


def find_game_exe() -> str:
    """Locates Game.exe and refuses any binary that is not the pinned release."""
    path = os.path.expanduser(os.environ.get("SUPERRTP_WOLF_GAME_EXE", DEFAULT_GAME_EXE))
    if not os.path.isfile(path):
        raise FileNotFoundError(f"WOLF Game.exe not found at {path}. Run tools/install_wolf_ci.sh first.")
    actual = sha256_file(path)
    if actual != PINNED_GAME_EXE_SHA256:
        raise ValueError(f"Game.exe SHA-256 mismatch: expected {PINNED_GAME_EXE_SHA256}, got {actual}")
    return path


def find_wine() -> str:
    return find_tool("wine", ("~/.local/bin/wine",))


def wine_version(wine: str) -> str:
    code, out, err = run_to_completion([wine, "--version"], timeout=60)
    text = (out or err).strip()
    if code != 0 or not text:
        raise RuntimeError(f"Could not read Wine version (exit {code}): {err.strip()}")
    return text.splitlines()[0]


# A dedicated, git-ignored Wine prefix, so results never depend on the user's own ~/.wine.
WINE_PREFIX = os.environ.get("SUPERRTP_WINEPREFIX", repo_path(".cache", "wineprefix"))

# Wine resolves font names through the host's fontconfig, so the fixture's "Courier" text
# (seen with WINEDEBUG=+font) became Courier New where the Microsoft core fonts are
# installed and Wine's bundled courier.ttf elsewhere, changing the glyphs
# verify_wolf_runtime reads. A private fontconfig configuration with no font directories
# hides the host fonts from Wine only, leaving just the fonts shipped with Wine itself.
FONTCONFIG_DIR = repo_path(".cache", "wine-fontconfig")
FONTCONFIG_FILE = os.path.join(FONTCONFIG_DIR, "fonts.conf")

# Keep Wine from offering to download Mono/Gecko installers; the runtime needs neither.
WINE_ENV = {"WINEPREFIX": WINE_PREFIX, "FONTCONFIG_FILE": FONTCONFIG_FILE, "WINEDLLOVERRIDES": "mscoree,mshtml=",
            "WINEDEBUG": os.environ.get("WINEDEBUG", "fixme-all")}


def _write_fontconfig() -> None:
    os.makedirs(FONTCONFIG_DIR, exist_ok=True)
    cache = os.path.join(FONTCONFIG_DIR, "cache")
    with open(FONTCONFIG_FILE, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0"?>\n<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">\n'
                f"<fontconfig><cachedir>{cache}</cachedir></fontconfig>\n")


def prepare_wine_prefix(wine: str, timeout: float = 300.0) -> None:
    """
    Creates or updates the Wine prefix (WINE_PREFIX) before any timed capture. The first
    Wine start on a fresh machine builds the prefix, which can take far longer than a
    render wait.
    """
    os.makedirs(WINE_PREFIX, exist_ok=True)
    _write_fontconfig()
    with xvfb_display(SCREEN_W, SCREEN_H) as display:
        code, _, err = run_to_completion([wine, "wineboot", "--init"], env=x11_env(display, **WINE_ENV), timeout=timeout)
    if code != 0:
        raise RuntimeError(f"wineboot failed (exit {code}): {err.strip()[-2000:]}")


def sanitize_wine_log(raw_log: str) -> str:
    """Normalizes run-specific noise (temp dirs, thread ids, pointers) so logs are comparable across runs."""
    s = portable_paths(raw_log)
    s = re.sub(r"superrtp_wolf_[A-Za-z0-9_]+", "superrtp_wolf_run", s)
    s = re.sub(r"^[0-9a-f]{4}:", "TID:", s, flags=re.MULTILINE)
    s = re.sub(r"0x[0-9a-fA-F]+", "0xHEX", s)
    s = re.sub(r"hwnd [0-9a-fA-F]+", "hwnd HWND", s)
    s = re.sub(r"iface [0-9a-fA-F]+", "iface IFACE", s)
    s = re.sub(r"\([0-9a-fA-F]{8}\)->\([0-9a-fA-F]{8}\)", "(PTR)->(PTR)", s)
    s = re.sub(r"Type FFFFFFFA, [0-9a-fA-F]{8}", "Type FFFFFFFA, PTR", s)
    lines = [line.rstrip() for line in s.splitlines() if line.strip() and "X connection to" not in line]
    return "\n".join(lines) + "\n"


class WolfSession:
    """Result of one Game.exe run: the accepted screenshot, Wine output and raw Game_ErrorLog.txt bytes (if written)."""

    def __init__(self, screenshot: str, log: str, error_log: bytes):
        self.screenshot = screenshot
        self.log = log
        self.error_log = error_log


def run_session(fixture_dir: str, game_exe: str, wine: str, output_png: str, is_ready,
                charachip_png: str = None, map_override: bytes = None, timeout: float = READY_TIMEOUT_S) -> WolfSession:
    """
    Runs Game.exe on a copy of `fixture_dir` until `is_ready(png_path)` accepts a screen grab.

    `charachip_png` is installed as Data/CharaChip/SuperRTP_Calibration.png (None = negative
    control); `map_override` replaces Data/MapData/SampleMap.mps. `is_ready` returns False to
    keep waiting and raises to report why a frame was rejected. On timeout the last
    rejection and the Wine output are included in the error, and `output_png` is untouched.
    """
    _write_fontconfig()
    with tempfile.TemporaryDirectory(prefix="superrtp_wolf_") as tmp:
        game_dir = os.path.join(tmp, "game")
        shutil.copytree(fixture_dir, game_dir)
        shutil.copy2(game_exe, os.path.join(game_dir, "Game.exe"))
        if charachip_png:
            os.makedirs(os.path.join(game_dir, "Data", "CharaChip"), exist_ok=True)
            shutil.copy2(charachip_png, os.path.join(game_dir, "Data", "CharaChip", "SuperRTP_Calibration.png"))
        if map_override is not None:
            with open(os.path.join(game_dir, "Data", "MapData", "SampleMap.mps"), "wb") as f:
                f.write(map_override)

        out_path, err_path = os.path.join(tmp, "stdout.log"), os.path.join(tmp, "stderr.log")
        failure = None
        with xvfb_display(SCREEN_W, SCREEN_H) as display, open(out_path, "w") as out_f, open(err_path, "w") as err_f:
            env = x11_env(display, **WINE_ENV)
            with managed(spawn([wine, "Game.exe"], env=env, cwd=game_dir, stdout=out_f, stderr=err_f)):
                try:
                    poll_screen(display, SCREEN_W, SCREEN_H, is_ready, output_png, timeout, POLL_INTERVAL_S)
                except TimeoutError as exc:
                    failure = exc

        with open(out_path, encoding="utf-8", errors="replace") as f:
            log = f.read()
        with open(err_path, encoding="utf-8", errors="replace") as f:
            log = sanitize_wine_log(log + "\n" + f.read())
        if failure:
            tail = "\n".join(log.splitlines()[-25:])
            raise TimeoutError(f"WOLF Game.exe: {failure}\nWine output (tail):\n{tail}") from failure
        error_log_path = os.path.join(game_dir, "Game_ErrorLog.txt")
        error_log = b""
        if os.path.exists(error_log_path):
            with open(error_log_path, "rb") as f:
                error_log = f.read()
    return WolfSession(output_png, log, error_log)
