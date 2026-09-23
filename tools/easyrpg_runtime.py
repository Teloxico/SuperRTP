#!/usr/bin/env python3
"""
EasyRPG Player driver shared by the RPG Maker 2000/2003 runtime verifiers
(tools/verify_runtime.py for CharSet, tools/verify_chipset_runtime.py for ChipSet).

EasyRPG renders the native 320x240 screen at 2x into a 640x480 fullscreen window
under Xvfb. Positive controls point `--rtp-path` at a generated SuperRTP pack;
negative controls pass `--no-rtp` so the missing-asset diagnostic is isolated.

Screens are captured by polling until they pass their check, and input is sent as real
X11 key presses. EasyRPG's --replay-input is not used: its reader fires an input only
when the frame counter equals the recorded frame (src/input_source.cpp), and in practice
recorded turns were intermittently never applied, leaving the hero facing down.
"""

import contextlib
import os
import re

from repo import portable_paths
from runtime_harness import find_tool, managed, poll_screen, run_to_completion, spawn, x11_env, xvfb_display

PINNED_EASYRPG_VERSION = "0.8.1.1"
SCREEN_W, SCREEN_H = 640, 480


ENGINE_MODES = {"rm2000": "rpg2k", "rm2003": "rpg2k3"}


# EasyRPG draws missing-asset warnings as yellow text in a banner across the top of
# the screen (observed in every negative-control capture at 0.8.1.1).
WARNING_TEXT_RGB = (255, 255, 0)
WARNING_BANNER_ROWS = 24
MIN_WARNING_TEXT_PIXELS = 500


def warning_text_pixels(pixels) -> int:
    """Count of warning-text pixels in the top banner of a decoded 640x480 screenshot."""
    return sum(row.count(WARNING_TEXT_RGB) for row in pixels[:WARNING_BANNER_ROWS])


def require_warning_banner(pixels) -> int:
    count = warning_text_pixels(pixels)
    if count < MIN_WARNING_TEXT_PIXELS:
        raise ValueError(f"Negative control missing EasyRPG warning banner: {count} warning-text pixels, expected >= {MIN_WARNING_TEXT_PIXELS}")
    return count


def find_player() -> str:
    return find_tool("easyrpg-player")


def player_version(player: str) -> str:
    """First line of `easyrpg-player --version`, e.g. 'EasyRPG Player 0.8.1.1 (2025-06-02)'."""
    code, out, err = run_to_completion([player, "--version"], timeout=15)
    line = (out or err).strip().splitlines()[0] if (out or err).strip() else ""
    if code != 0 or not line:
        raise RuntimeError(f"Could not read EasyRPG Player version (exit {code})")
    return line


def check_pinned_version(version_line: str) -> None:
    if not re.search(r"\b" + re.escape(PINNED_EASYRPG_VERSION) + r"\b", version_line or ""):
        raise ValueError(f"EasyRPG version pin violation: expected {PINNED_EASYRPG_VERSION} in '{version_line}'")


def player_command(player: str, fixture_dir: str, engine: str, rtp_dir: str = None, log_file: str = None) -> list:
    """Command line for a headless verification session (rtp_dir=None disables the RTP)."""
    cmd = [player, "--project-path", fixture_dir]
    cmd += ["--rtp-path", rtp_dir] if rtp_dir else ["--no-rtp"]
    cmd += ["--engine", engine, "--new-game", "--disable-audio", "--no-pause-focus-lost",
            "--fullscreen", "--no-log-color", "--seed", "42"]
    if log_file:
        cmd += ["--log-file", log_file]
    return cmd


def _session_env(display: str) -> dict:
    return x11_env(display, SDL_VIDEODRIVER="x11", SDL_AUDIODRIVER="dummy")


def _prepare_log(log_file: str) -> None:
    # EasyRPG opens --log-file in append mode (docs/engine-facts.md); start each run empty.
    if log_file and os.path.exists(log_file):
        os.remove(log_file)


def finalize_log(log_file: str) -> str:
    """Rewrites the session log with portable paths and returns its text."""
    if not os.path.exists(log_file):
        raise FileNotFoundError(f"EasyRPG did not write its log file: {log_file}")
    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
        text = portable_paths(f.read())
    with open(log_file, "w", encoding="utf-8") as f:
        f.write(text)
    return text


@contextlib.contextmanager
def session(cmd: list, log_file: str = None):
    """
    Runs one player session under a private Xvfb display and yields that display.
    The session is always stopped on exit, and its log is then made portable.
    """
    _prepare_log(log_file)
    with xvfb_display(SCREEN_W, SCREEN_H) as display:
        with managed(spawn(cmd, env=_session_env(display))):
            yield display
    if log_file:
        finalize_log(log_file)


def wait_for(display: str, is_ready, out_png: str, timeout: float = 30.0) -> None:
    """
    Polls the screen until `is_ready(png)` accepts it (runtime_harness.poll_screen).

    The session log cannot be used as a readiness signal: EasyRPG writes it out on exit,
    so log content is checked after the session ends.
    """
    poll_screen(display, SCREEN_W, SCREEN_H, is_ready, out_png, timeout)
