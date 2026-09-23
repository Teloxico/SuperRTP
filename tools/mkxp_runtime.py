#!/usr/bin/env python3
"""
mkxp-z driver shared by the RPG Maker XP / VX / VX Ace runtime verifiers.

Each fixture (tests/fixtures/<target>_character_min) is a clean-room `fixture.rb` run as
mkxp-z's customScript. It draws a test pad, loads the character sheet through the RTP
search path, prints SUPERRTP_* markers, and exits 0 (loaded) or 1 (missing asset).

mkxp-z is launched from a temporary working directory holding a generated mkxp.json:
with the `workdir_current` build option, `gameFolder` resolves against the working
directory (docs/engine-facts.md), so absolute paths are written there. The evidence
records a portable copy of that configuration with repository-relative paths.

The pinned build is produced by tools/install_mkxp_z_ci.sh, which writes
mkxp-z.build.json next to the binary; that metadata is required, not optional.
"""

import json
import os
import re
import shutil
import tempfile
import time

from repo import REPO_ROOT, load_json, portable_paths
from runtime_harness import (find_tool, finish_recording, managed, pick_video_frames, run_to_completion,
                             start_screen_recording, x11_env, xvfb_display)

PINNED_MKXP_COMMIT = "826929eeb3ebc4b887c011604919217a790770f4"
BUILD_CONFIG_REVISION = "buildcfg2"
MKXP_FALLBACK_PATHS = ("~/.local/bin/mkxp-z",)
RECORDER_WARMUP_S = 0.3
# Recording windows. The fixtures draw for about one second and exit; the extra time
# absorbs slow start-ups, since the captured frame is chosen by content, not by time.
POSITIVE_RECORD_SECONDS = 5
NEGATIVE_RECORD_SECONDS = 4
SCREEN_SIZES = {1: (640, 480), 2: (544, 416), 3: (544, 416)}


def find_mkxp() -> str:
    return find_tool("mkxp-z", MKXP_FALLBACK_PATHS)


def check_build_metadata(meta: dict, where: str = "build metadata") -> dict:
    """Requires a build of the pinned commit with the configuration the fixtures depend on."""
    if not isinstance(meta, dict):
        raise ValueError(f"Invalid mkxp-z {where}: expected JSON object")
    expected = {"runtime": "mkxp-z", "pinned_commit": PINNED_MKXP_COMMIT, "workdir_current": True,
                "static_executable": False, "shared_fluid": False, "build_config_revision": BUILD_CONFIG_REVISION}
    for key, value in expected.items():
        if meta.get(key) != value:
            raise ValueError(f"Invalid {key} in {where}: expected {value!r}, got {meta.get(key)!r}")
    mri = meta.get("mri_version")
    if not isinstance(mri, str) or not mri.strip():
        raise ValueError(f"Invalid or empty mri_version in {where}: {mri!r}")
    return meta


def read_build_metadata(mkxp_bin: str) -> dict:
    """Loads and checks mkxp-z.build.json from the binary's directory."""
    meta_path = os.path.join(os.path.dirname(os.path.abspath(mkxp_bin)), "mkxp-z.build.json")
    if not os.path.exists(meta_path):
        raise FileNotFoundError(f"mkxp-z build metadata '{meta_path}' not found; it is required to prove runtime provenance "
                                "(tools/install_mkxp_z_ci.sh writes it)")
    return check_build_metadata(load_json(meta_path), where=f"build metadata {meta_path}")


def build_configuration_summary(meta: dict) -> dict:
    """The build options recorded in RMXP/RMVX evidence as `mkxp_z_build_configuration`."""
    return {key: meta[key] for key in ("workdir_current", "static_executable", "mri_version", "shared_fluid", "build_config_revision")}


def check_build_configuration(cfg: dict) -> None:
    """Validates an evidence `mkxp_z_build_configuration` block."""
    if not isinstance(cfg, dict):
        raise ValueError("Missing mkxp_z_build_configuration in evidence")
    if cfg.get("workdir_current") is not True:
        raise ValueError("mkxp_z_build_configuration.workdir_current must be true")
    if cfg.get("static_executable") is not False:
        raise ValueError("mkxp_z_build_configuration.static_executable must be false")
    if not isinstance(cfg.get("mri_version"), str) or not cfg["mri_version"].strip():
        raise ValueError("mkxp_z_build_configuration.mri_version must be non-empty string")
    if cfg.get("shared_fluid") is not False:
        raise ValueError("mkxp_z_build_configuration.shared_fluid must be false")
    if cfg.get("build_config_revision") != BUILD_CONFIG_REVISION:
        raise ValueError(f"mkxp_z_build_configuration.build_config_revision mismatch: expected '{BUILD_CONFIG_REVISION}', got '{cfg.get('build_config_revision')}'")


def portable_config(rgss_version: int, fixture_rel: str, rtp_rel: list) -> dict:
    """mkxp.json contents with repository-relative paths, as recorded in evidence."""
    return {"rgssVersion": rgss_version, "gameFolder": fixture_rel, "customScript": "fixture.rb",
            "pathCache": True, "RTP": list(rtp_rel)}


def check_portable_config(conf: dict, rgss_version: int, fixture_rel: str, rtp_rel: list, label: str) -> None:
    """Requires a recorded portable configuration to describe exactly the intended run."""
    expected = portable_config(rgss_version, fixture_rel, rtp_rel)
    if not isinstance(conf, dict):
        raise ValueError(f"Missing {label} in evidence")
    for key, value in expected.items():
        if conf.get(key) != value:
            raise ValueError(f"{label} {key} mismatch: expected {value!r}, got {conf.get(key)!r}")
    extra = set(conf) - set(expected)
    if extra:
        raise ValueError(f"{label} has unexpected keys: {sorted(extra)}")


class MkxpRun:
    """Result of one mkxp-z session."""

    def __init__(self, exit_code: int, stdout: str, stderr: str):
        self.exit_code = exit_code
        self.stdout = portable_paths(stdout)
        self.stderr = portable_paths(stderr)

    @property
    def log(self) -> str:
        return self.stdout + "\n" + self.stderr

    @property
    def version(self) -> str:
        match = re.search(r"MKXP-Z VERSION:\s*(\S+)", self.stdout)
        if not match:
            raise ValueError("mkxp-z did not print 'MKXP-Z VERSION:'; the fixture script may not have run")
        return match.group(1)


def run_session(mkxp_bin: str, conf: dict, screenshot_path: str, record_seconds: float, scene_drawn,
                timeout: float = 60.0, require_frame: bool = True) -> MkxpRun:
    """
    Runs mkxp-z with `conf` (paths repository-relative) under Xvfb and records the screen.
    The saved screenshot is the middle of the stable run of samples for which
    `scene_drawn(rgb24_bytes)` is true (runtime_harness.pick_video_frames), so start-up
    delays cannot shift which frame is captured. Returns the exit code and output.
    If no frame qualifies, the recording is kept as `<screenshot_path>.failed.mkv`.
    With `require_frame=False` no screenshot is taken (the run is judged by its output).
    """
    width, height = SCREEN_SIZES[conf["rgssVersion"]]
    runtime_conf = dict(conf, gameFolder=os.path.join(REPO_ROOT, conf["gameFolder"]),
                        RTP=[os.path.join(REPO_ROOT, p) for p in conf["RTP"]])
    with tempfile.TemporaryDirectory(prefix="superrtp_mkxp_") as workdir:
        with open(os.path.join(workdir, "mkxp.json"), "w", encoding="utf-8") as f:
            json.dump(runtime_conf, f, indent=2)
        video = os.path.join(workdir, "session.mkv")
        with xvfb_display(width, height) as display:
            env = x11_env(display, SDL_VIDEODRIVER="x11", SDL_AUDIODRIVER="dummy", ALSOFT_DRIVERS="null", LIBGL_ALWAYS_SOFTWARE="1")
            recorder = start_screen_recording(display, width, height, video, record_seconds)
            with managed(recorder):
                time.sleep(RECORDER_WARMUP_S)
                code, out, err = run_to_completion([mkxp_bin], env=env, cwd=workdir, timeout=timeout)
                finish_recording(recorder, timeout=record_seconds + 30)
        if not require_frame:
            return MkxpRun(code, out, err)
        try:
            pick_video_frames(video, width, height, lambda rgb: "scene" if scene_drawn(rgb) else None,
                              ["scene"], {"scene": screenshot_path})
        except ValueError as exc:
            shutil.copyfile(video, screenshot_path + ".failed.mkv")
            raise ValueError(f"{exc} (mkxp-z exit {code}; recording kept as {screenshot_path}.failed.mkv; "
                             f"stderr tail: {err.strip()[-500:]!r})") from exc
    return MkxpRun(code, out, err)
