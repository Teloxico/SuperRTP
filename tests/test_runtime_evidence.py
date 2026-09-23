"""
Runtime verification evidence: committed evidence must verify, every recorded fact must
be bound (tampering with any field or with screenshot pixels is rejected), and each
engine must pass a fresh live capture.

Live captures need the engines (EasyRPG Player, mkxp-z, WOLF Game.exe + Wine, Xvfb,
ffmpeg). They skip when a tool is missing unless SUPERRTP_REQUIRE_RUNTIME=1.
Captures write into temporary directories; committed artifacts are never modified.
"""

import copy
import json
import os
import shutil
import tempfile
import unittest
from dataclasses import dataclass, field

from support import REPO_ROOT, have, require, rewrite_screenshot

import verify_chipset_runtime as chipset
import verify_rmvx_runtime as rmvx
import verify_rmvxace_runtime as rmvxace
import verify_rmxp_runtime as rmxp
import verify_runtime as charset
import verify_wolf_runtime as wolf_verifier
import wolf_runtime
from repo import sha256_file

MAGENTA = (255, 0, 255)


@dataclass
class Case:
    name: str
    artifacts_dir: str
    verify: object                 # (evidence_path, artifacts_dir) -> None, raises on failure
    capture: object                # (artifacts_dir) -> None
    tools: tuple                   # executables the live capture needs
    shot: str                      # a positive screenshot to tamper with
    region: tuple                  # (x0, y0, x1, y1) inside the rendered sprite(s)
    rehash: object                 # (evidence, sha) -> None, updates the recorded hash of `shot`
    descriptive: set = field(default_factory=set)  # leaf paths that describe the host rather than bind a fact


def _art(*parts):
    return os.path.join(REPO_ROOT, "artifacts", "runtime", *parts)


def _screenshots_table(name):
    return lambda ev, sha: ev["screenshots"].__setitem__(name, sha)


def _wolf_available():
    try:
        wolf_runtime.find_game_exe()
        return have("wine", "~/.local/bin/wine")
    except (FileNotFoundError, ValueError):
        return False


CASES = []
for t in ("rm2000", "rm2003"):
    CASES.append(Case(f"{t}-charset", _art(t, "charset"),
                      lambda e, a, t=t: charset.verify_evidence_chain(t, evidence_path=e, artifacts_dir=a),
                      lambda a, t=t: charset.run_capture_and_record(t, a), ("easyrpg-player",),
                      f"{t}_charset_down.png", (300, 180, 360, 240), _screenshots_table(f"{t}_charset_down.png")))
    CASES.append(Case(f"{t}-chipset", _art(t, "chipset"),
                      lambda e, a, t=t: chipset.verify_evidence_chain(t, evidence_path=e, artifacts_dir=a),
                      lambda a, t=t: chipset.run_capture_and_record(t, a), ("easyrpg-player",),
                      f"{t}_chipset_positive.png", (64, 64, 96, 96), _screenshots_table(f"{t}_chipset_positive.png")))
CASES += [
    Case("rmxp", _art("rmxp", "character"), lambda e, a: rmxp.verify_evidence_chain(evidence_path=e, artifacts_dir=a),
         lambda a: rmxp.run_capture_and_record(a), ("mkxp-z",), "rmxp_character_positive.png", (296, 200, 320, 224),
         _screenshots_table("rmxp_character_positive.png"), {("mkxp_z_build_configuration", "mri_version")}),
    Case("rmvx", _art("rmvx", "character"), lambda e, a: rmvx.verify_evidence_chain(e, artifacts_dir=a),
         lambda a: rmvx.run_capture(rmvx.get_target_config(a)), ("mkxp-z",), "rmvx_character_positive.png", (150, 100, 180, 130),
         _screenshots_table("rmvx_character_positive.png"), {("mkxp_z_build_configuration", "mri_version")}),
    Case("rmvxace", _art("rmvxace", "character"), lambda e, a: rmvxace.verify_evidence_chain(e, a),
         lambda a: rmvxace.run_capture(rmvxace.get_target_config(a)), ("mkxp-z",), "rmvxace_character_positive.png",
         (150, 100, 180, 130), lambda ev, sha: ev.__setitem__("positive_screenshot_sha256", sha), {("build_metadata", "mri_version")}),
    Case("wolf", _art("wolf", "character"), lambda e, a: wolf_verifier.verify_evidence_chain(e, artifacts_dir=a),
         lambda a: wolf_verifier.run_capture(wolf_verifier.get_target_config(a)), ("wine",), "wolf_character_positive.png",
         (120, 64, 160, 120), lambda ev, sha: ev["positive_screenshots"].__setitem__("wolf_character_positive.png", sha),
         {("runtime_environment_metadata",)}),
]


def _leaf_paths(value, path=()):
    """Paths to every scalar or list leaf of a JSON value."""
    if isinstance(value, dict) and value:
        for key, child in value.items():
            yield from _leaf_paths(child, path + (key,))
    else:
        yield path


def _tampered(value):
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float)):
        return value + 1
    if isinstance(value, list):
        return value[:-1] if value else ["tampered"]
    return "tampered"


def _set(obj, path, value):
    for key in path[:-1]:
        obj = obj[key]
    obj[path[-1]] = value


def _get(obj, path):
    for key in path:
        obj = obj[key]
    return obj


class TestRuntimeEvidence(unittest.TestCase):
    def test_committed_evidence_verifies(self):
        for case in CASES:
            with self.subTest(case.name):
                case.verify(None, case.artifacts_dir)

    def test_every_evidence_field_is_bound(self):
        """Changing or removing any recorded fact must make verification fail."""
        for case in CASES:
            with open(os.path.join(case.artifacts_dir, "verification_evidence.json")) as f:
                evidence = json.load(f)
            mutations = []
            for key in evidence:
                mutations.append((f"remove {key}", lambda ev, key=key: ev.pop(key)))
            for path in _leaf_paths(evidence):
                if any(path[:len(d)] == d for d in case.descriptive):
                    continue
                mutations.append(("/".join(map(str, path)), lambda ev, path=path: _set(ev, path, _tampered(_get(ev, path)))))
            with tempfile.TemporaryDirectory(prefix="superrtp_tamper_") as tmp:
                path = os.path.join(tmp, "evidence.json")
                for label, mutate in mutations:
                    tampered = copy.deepcopy(evidence)
                    mutate(tampered)
                    with open(path, "w") as f:
                        json.dump(tampered, f)
                    with self.subTest(case=case.name, mutation=label), self.assertRaises((ValueError, FileNotFoundError)):
                        case.verify(path, case.artifacts_dir)

    def test_screenshot_pixel_tampering_is_detected(self):
        """A rehashed screenshot with altered sprite pixels must still fail the pixel checks."""
        for case in CASES:
            with self.subTest(case.name), tempfile.TemporaryDirectory(prefix="superrtp_pixels_") as tmp:
                artifacts = os.path.join(tmp, "artifacts")
                shutil.copytree(case.artifacts_dir, artifacts)
                x0, y0, x1, y1 = case.region
                rewrite_screenshot(os.path.join(artifacts, case.shot),
                                   lambda x, y, rgb, r=(x0, y0, x1, y1): MAGENTA if r[0] <= x < r[2] and r[1] <= y < r[3] else rgb)
                evidence_path = os.path.join(artifacts, "verification_evidence.json")
                with open(evidence_path) as f:
                    evidence = json.load(f)
                case.rehash(evidence, sha256_file(os.path.join(artifacts, case.shot)))
                with open(evidence_path, "w") as f:
                    json.dump(evidence, f)
                with self.assertRaises(ValueError):
                    case.verify(evidence_path, artifacts)


class TestLiveRuntimes(unittest.TestCase):
    """Fresh end-to-end captures through the real engines, verified with the same checks."""

    def _run(self, case):
        require(self, all(have(tool, f"~/.local/bin/{tool}") for tool in case.tools + ("Xvfb", "ffmpeg")),
                f"{case.name} runtime ({', '.join(case.tools)}, Xvfb, ffmpeg)")
        if case.name == "wolf":
            require(self, _wolf_available(), "WOLF Game.exe 3.717 and Wine")
        with tempfile.TemporaryDirectory(prefix=f"superrtp_live_{case.name}_") as tmp:
            case.capture(tmp)
            case.verify(None, tmp)


for _case in CASES:
    setattr(TestLiveRuntimes, f"test_{_case.name.replace('-', '_')}", lambda self, c=_case: self._run(c))


if __name__ == "__main__":
    unittest.main()
