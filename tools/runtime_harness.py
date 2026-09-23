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
import time


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


def require_tools(*names: str) -> dict:
    """Resolves several PATH executables at once; returns {name: path}."""
    return {name: find_tool(name) for name in names}


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
        raise RuntimeToolError(f"Screen recording did not finish within {timeout}s")
    if proc.returncode != 0:
        raise RuntimeToolError(f"ffmpeg recording failed (exit {proc.returncode}): {(err or b'').decode(errors='replace').strip()}")


def extract_frame(video_path: str, timestamp: str, output_png: str) -> None:
    """Writes the frame at `timestamp` (HH:MM:SS.fff) of `video_path` as a PNG."""
    ffmpeg = find_tool("ffmpeg")
    result = subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-ss", timestamp, "-i", video_path, "-frames:v", "1", output_png],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not os.path.exists(output_png):
        raise RuntimeToolError(f"ffmpeg frame extraction at {timestamp} failed: {result.stderr.strip()}")


def grab_screen(display: str, width: int, height: int, output_png: str) -> bool:
    """Captures a single frame of `display`; returns False if the grab failed."""
    ffmpeg = find_tool("ffmpeg")
    result = subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-f", "x11grab", "-draw_mouse", "0",
         "-video_size", f"{width}x{height}", "-i", f"{display}.0", "-vframes", "1", output_png],
        capture_output=True,
    )
    return result.returncode == 0 and os.path.exists(output_png)


def run_to_completion(cmd, env=None, cwd=None, timeout: float = 60.0):
    """Runs `cmd` in its own process group; returns (exit_code, stdout, stderr) as text."""
    proc = spawn(cmd, env=env, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _terminate(proc)
        raise RuntimeToolError(f"{os.path.basename(cmd[0])} did not exit within {timeout}s")
    return proc.returncode, out.decode("utf-8", errors="replace"), err.decode("utf-8", errors="replace")


def run_for(cmd, seconds: float, env=None, cwd=None):
    """
    Runs `cmd` for at most `seconds`, then stops it; returns (stdout, stderr) as text.

    Used for engines that never exit on their own (they stay on the title/map screen).
    """
    proc = spawn(cmd, env=env, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        out, err = proc.communicate(timeout=seconds)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            out, err = proc.communicate(timeout=3.0)
        except subprocess.TimeoutExpired:
            _terminate(proc)
            out, err = proc.communicate()
    return out.decode("utf-8", errors="replace"), err.decode("utf-8", errors="replace")
