#!/usr/bin/env python3
"""
Process helpers for driving real engine runtimes headlessly under Xvfb.

Design rules:
  - Commands are argument lists; nothing is passed through a shell, so paths with
    spaces or shell metacharacters are safe.
  - Xvfb picks its own free display via `-displayfd` (see docs/engine-facts.md), so
    concurrent runs never collide and no lock files are guessed at or deleted.
  - Scratch files live in per-run temporary directories, never at fixed /tmp paths.
  - Every child is started in its own process group and is always torn down, even
    when a capture step fails.
"""

import contextlib
import os
import shutil
import signal
import subprocess
import tempfile
import time


# Recordings are classified at this sample rate; a state must hold for MIN_STABLE_SAMPLES
# consecutive samples before a frame is taken from it.
SAMPLE_FPS = 10
MIN_STABLE_SAMPLES = 3


class RuntimeToolError(RuntimeError):
    """A required runtime or tool is missing or failed to start."""


def find_tool(name: str, fallbacks=()) -> str:
    """Absolute path of an executable from PATH or the given fallback locations."""
    found = shutil.which(name)
    if found:
        return found
    for candidate in fallbacks:
        candidate = os.path.expanduser(candidate)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    searched = ", ".join(["PATH"] + [os.path.expanduser(c) for c in fallbacks])
    raise RuntimeToolError(f"Required executable '{name}' not found (searched: {searched})")


def _terminate(proc, timeout: float = 3.0) -> None:
    """Stops a process group started with start_new_session=True: SIGTERM, then SIGKILL."""
    if proc is None or proc.poll() is not None:
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=timeout)
            return
        except subprocess.TimeoutExpired:
            continue


def spawn(cmd, env=None, cwd=None, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) -> subprocess.Popen:
    """Starts `cmd` in a new process group so it can be torn down as a unit."""
    return subprocess.Popen(cmd, env=env, cwd=cwd, stdout=stdout, stderr=stderr, start_new_session=True)


@contextlib.contextmanager
def managed(proc: subprocess.Popen, timeout: float = 3.0):
    """Context manager that always tears `proc` down on exit."""
    try:
        yield proc
    finally:
        _terminate(proc, timeout)


@contextlib.contextmanager
def xvfb_display(width: int, height: int, depth: int = 24, start_timeout: float = 10.0):
    """
    Starts a private Xvfb server and yields its DISPLAY string (e.g. ':3').

    Xvfb chooses a free display number itself and reports it through a pipe
    (`-displayfd`), which is also the readiness signal: the number is written only
    once the server accepts connections.
    """
    xvfb = find_tool("Xvfb")
    read_fd, write_fd = os.pipe()
    proc = subprocess.Popen(
        [xvfb, "-displayfd", str(write_fd), "-screen", "0", f"{width}x{height}x{depth}", "-nolisten", "tcp"],
        pass_fds=(write_fd,), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True,
    )
    os.close(write_fd)
    try:
        number = _read_display_number(read_fd, proc, start_timeout)
        yield f":{number}"
    finally:
        os.close(read_fd)
        _terminate(proc)
        if proc.stderr:
            proc.stderr.close()


def _read_display_number(read_fd: int, proc: subprocess.Popen, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    buf = b""
    os.set_blocking(read_fd, False)
    while time.monotonic() < deadline:
        try:
            chunk = os.read(read_fd, 64)
        except BlockingIOError:
            chunk = None
        if chunk:
            buf += chunk
            if buf.endswith(b"\n"):
                return buf.decode().strip()
        elif chunk == b"" or proc.poll() is not None:
            err = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
            raise RuntimeToolError(f"Xvfb exited before reporting a display: {err.strip()}")
        time.sleep(0.05)
    raise RuntimeToolError(f"Xvfb did not report a display within {timeout}s")


def x11_env(display: str, **extra: str) -> dict:
    """Current environment pointed at `display`, plus any extra variables."""
    env = os.environ.copy()
    env["DISPLAY"] = display
    env.update(extra)
    return env


def start_screen_recording(display: str, width: int, height: int, output_path: str, duration: float) -> subprocess.Popen:
    """
    Records `duration` seconds of `display` to a lossless RGB video.

    libx264rgb at CRF 0 keeps every pixel exact, so frames extracted later can be
    compared against target sheets without codec tolerance.
    """
    ffmpeg = find_tool("ffmpeg")
    return spawn([
        ffmpeg, "-y", "-loglevel", "error",
        "-f", "x11grab", "-draw_mouse", "0", "-video_size", f"{width}x{height}", "-i", f"{display}.0",
        "-c:v", "libx264rgb", "-crf", "0", "-preset", "ultrafast", "-t", str(duration), output_path,
    ], stderr=subprocess.PIPE)


def finish_recording(proc: subprocess.Popen, timeout: float) -> None:
    """Waits for a recording started by `start_screen_recording` and checks it succeeded."""
    try:
        _, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _terminate(proc)
        raise RuntimeToolError(f"Screen recording did not finish within {timeout}s") from None
    if proc.returncode != 0:
        raise RuntimeToolError(f"ffmpeg recording failed (exit {proc.returncode}): {(err or b'').decode(errors='replace').strip()}")


def sample_video_frames(video_path: str, width: int, height: int, fps: float) -> list:
    """Decodes `video_path` resampled to `fps` into raw RGB24 frames (one bytes object each)."""
    ffmpeg = find_tool("ffmpeg")
    result = subprocess.run([ffmpeg, "-loglevel", "error", "-i", video_path, "-vf", f"fps={fps}",
                             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
    frame_size = width * height * 3
    if result.returncode != 0 or not result.stdout or len(result.stdout) % frame_size:
        raise RuntimeToolError(f"ffmpeg could not sample {video_path}: {result.stderr.decode(errors='replace').strip()}")
    return [result.stdout[i:i + frame_size] for i in range(0, len(result.stdout), frame_size)]


def save_sampled_frame(video_path: str, fps: float, index: int, output_png: str, expected_rgb: bytes) -> None:
    """
    Writes sample `index` of `sample_video_frames(video_path, ..., fps)` as a PNG and
    confirms the PNG holds exactly the pixels that were classified.
    """
    from png_utils import read_png  # local import: png_utils has no process dependencies
    ffmpeg = find_tool("ffmpeg")
    result = subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", video_path,
                             "-vf", f"fps={fps},select=eq(n\\,{index})", "-frames:v", "1", output_png],
                            capture_output=True, text=True)
    if result.returncode != 0 or not os.path.exists(output_png):
        raise RuntimeToolError(f"ffmpeg could not extract sample {index}: {result.stderr.strip()}")
    if read_png(output_png).pixels != expected_rgb:
        raise RuntimeToolError(f"Extracted frame {index} of {video_path} differs from the classified sample")


def stable_runs(labels: list) -> list:
    """Collapses per-sample labels into [(label, first_index, length)] runs, skipping None."""
    runs = []
    for i, label in enumerate(labels):
        if runs and runs[-1][0] == label and runs[-1][1] + runs[-1][2] == i:
            runs[-1] = (label, runs[-1][1], runs[-1][2] + 1)
        elif label is not None:
            runs.append((label, i, 1))
    return runs


def pick_video_frames(video: str, width: int, height: int, classify, wanted: list, out_paths: dict) -> dict:
    """
    Saves one frame per state in `wanted`, chosen by what the frames show rather than when.

    Every sample of the recording is labelled by `classify(rgb24_bytes)` (a state or None).
    Each wanted state must appear as a stable run (at least MIN_STABLE_SAMPLES long) after
    the previous one, in order; the middle sample of that run is written to out_paths[state].
    Wall-clock offsets are not used because engine start-up time varies with machine load.
    """
    frames = sample_video_frames(video, width, height, SAMPLE_FPS)
    labels = [classify(frame) for frame in frames]
    runs = stable_runs(labels)
    chosen, cursor = {}, 0
    for state in wanted:
        run = next((r for r in runs if r[0] == state and r[1] >= cursor and r[2] >= MIN_STABLE_SAMPLES), None)
        if run is None:
            observed = [(label, length) for label, _, length in runs]
            raise ValueError(f"State '{state}' was not observed as a stable run in order {wanted}; observed runs: {observed}")
        index = run[1] + run[2] // 2
        save_sampled_frame(video, SAMPLE_FPS, index, out_paths[state], frames[index])
        chosen[state] = index
        cursor = run[1] + run[2]
    return chosen


def grab_screen(display: str, width: int, height: int, output_png: str) -> bool:
    """Captures a single frame of `display`; returns False if the grab failed."""
    ffmpeg = find_tool("ffmpeg")
    result = subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-f", "x11grab", "-draw_mouse", "0",
         "-video_size", f"{width}x{height}", "-i", f"{display}.0", "-vframes", "1", output_png],
        capture_output=True,
    )
    return result.returncode == 0 and os.path.exists(output_png)


def press_key(display: str, key: str, hold: float = 0.08) -> None:
    """Presses and releases an X11 keysym (e.g. 'Left') on `display` through XTEST (xdotool)."""
    xdotool = find_tool("xdotool", ("~/.local/bin/xdotool",))
    env = x11_env(display)
    for action in ("keydown", "keyup"):
        result = subprocess.run([xdotool, action, key], env=env, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeToolError(f"xdotool {action} {key} failed: {result.stderr.strip()}")
        if action == "keydown":
            time.sleep(hold)


def poll_screen(display: str, width: int, height: int, is_ready, output_png: str,
                timeout: float, interval: float = 0.5) -> None:
    """
    Grabs `display` every `interval` seconds until `is_ready(png_path)` accepts a frame,
    then copies that frame to `output_png`.

    `is_ready` returns False to keep waiting and raises ValueError to reject a frame with
    a reason; on timeout the last reason is reported and `output_png` is left untouched.
    """
    last_reason = "no frame captured yet"
    with tempfile.TemporaryDirectory(prefix="superrtp_poll_") as tmp:
        candidate = os.path.join(tmp, "frame.png")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            time.sleep(interval)
            if not grab_screen(display, width, height, candidate):
                last_reason = "screen grab failed"
                continue
            try:
                if is_ready(candidate):
                    shutil.copyfile(candidate, output_png)
                    return
                last_reason = "frame not ready"
            except ValueError as exc:
                last_reason = str(exc)
    raise TimeoutError(f"Expected screen state not reached within {timeout}s for {output_png}. Last rejection: {last_reason}")


def run_to_completion(cmd, env=None, cwd=None, timeout: float = 60.0):
    """Runs `cmd` in its own process group; returns (exit_code, stdout, stderr) as text."""
    proc = spawn(cmd, env=env, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _terminate(proc)
        raise RuntimeToolError(f"{os.path.basename(cmd[0])} did not exit within {timeout}s") from None
    return proc.returncode, out.decode("utf-8", errors="replace"), err.decode("utf-8", errors="replace")
