"""
Clean-room test fixture integrity (tests/fixtures/*).

  - Every fixture file matches the hash in its fixture_manifest.json.
  - The 2k-family fixtures regenerate byte for byte: graphics from
    tools/generate_fixture_graphics.py, LCF binaries from tools/generate_fixture.cpp
    compiled against liblcf 0.8.1 (needs a C++ compiler and liblcf via pkg-config).
  - The WOLF map parser round-trips the fixture map, which the directional captures rely on.
"""

import glob
import os
import re
import shutil
import subprocess
import tempfile
import unittest

from support import REPO_ROOT, require

import generate_fixture_graphics as graphics
from repo import load_json, sha256_bytes, sha256_file
from wolf_map_utils import compress_mps, decompress_mps, dump_mps_body, parse_mps_body

FIXTURES = os.path.join(REPO_ROOT, "tests", "fixtures")
LCF_FIXTURES = {"rm2000_min": ("rm2000", "charset"), "rm2003_min": ("rm2003", "charset"),
                "rm2000_chipset_min": ("rm2000", "chipset"), "rm2003_chipset_min": ("rm2003", "chipset")}
LCF_BINARIES = ("Map0001.lmu", "RPG_RT.ini", "RPG_RT.ldb", "RPG_RT.lmt")
LIBLCF_PIN = re.compile(r"^0\.8\.1(_\d+)?(-.*)?$")


def manifest_hashes(manifest: dict) -> dict:
    """File -> sha256 from any of the three fixture manifest layouts in use."""
    hashes = dict(manifest.get("files", {}))
    for rel, value in list(hashes.items()):
        if isinstance(value, dict):
            hashes[rel] = value["sha256"]
    for section in ("project_data", "support_assets"):
        hashes.update({rel: info["sha256"] for rel, info in manifest.get(section, {}).items()})
    return hashes


def _liblcf_env():
    env = os.environ.copy()
    brew_pc = "/home/linuxbrew/.linuxbrew/opt/liblcf/lib/pkgconfig"
    if os.path.isdir(brew_pc):
        env["PKG_CONFIG_PATH"] = os.pathsep.join(filter(None, [brew_pc, env.get("PKG_CONFIG_PATH")]))
    return env


class TestFixtures(unittest.TestCase):
    def test_every_fixture_matches_its_manifest(self):
        manifests = sorted(glob.glob(os.path.join(FIXTURES, "*", "fixture_manifest.json")))
        self.assertEqual(len(manifests), 9)
        for path in manifests:
            fixture = os.path.dirname(path)
            manifest = load_json(path)
            hashes = manifest_hashes(manifest)
            self.assertTrue(hashes, path)
            for rel, digest in hashes.items():
                with self.subTest(fixture=os.path.basename(fixture), file=rel):
                    self.assertEqual(sha256_file(os.path.join(fixture, rel)), digest)
            for key in ("generator", "graphics_generator"):
                if f"{key}_source" in manifest:
                    self.assertEqual(sha256_file(os.path.join(REPO_ROOT, manifest[f"{key}_source"])), manifest[f"{key}_sha256"],
                                     f"{manifest[f'{key}_source']} changed; regenerate the fixtures and their manifests")

    def test_fixture_graphics_regenerate(self):
        generated = {"ChipSet/ChipSet.png": graphics.generate_minimal_chipset(),
                     "System/System.png": graphics.generate_minimal_system(),
                     "CharSet/Actor1.png": graphics.generate_minimal_charset(),
                     "CharSet/Hero1.png": graphics.generate_minimal_charset()}
        for name in LCF_FIXTURES:
            hashes = manifest_hashes(load_json(os.path.join(FIXTURES, name, "fixture_manifest.json")))
            for rel, data in generated.items():
                if rel in hashes:
                    self.assertEqual(sha256_bytes(data), hashes[rel], f"{name}/{rel}")

    def test_lcf_binaries_regenerate_with_pinned_liblcf(self):
        cxx = shutil.which("g++") or shutil.which("clang++")
        require(self, bool(cxx) and bool(shutil.which("pkg-config")), "C++ compiler and pkg-config")
        env = _liblcf_env()
        version = subprocess.run(["pkg-config", "--modversion", "liblcf"], env=env, capture_output=True, text=True)
        require(self, version.returncode == 0, "liblcf (pkg-config)")
        self.assertRegex(version.stdout.strip(), LIBLCF_PIN, "liblcf version pin violation (expected 0.8.1)")
        flags = subprocess.run(["pkg-config", "--cflags", "--libs", "liblcf"], env=env, capture_output=True, text=True, check=True).stdout.split()
        libdir = subprocess.run(["pkg-config", "--variable=libdir", "liblcf"], env=env, capture_output=True, text=True).stdout.strip()

        with tempfile.TemporaryDirectory(prefix="superrtp_lcf_") as tmp:
            binary = os.path.join(tmp, "generate_fixture")
            rpath = [f"-Wl,-rpath,{libdir}"] if libdir else []
            subprocess.run([cxx, "-O2", "-std=c++17", os.path.join(REPO_ROOT, "tools", "generate_fixture.cpp"), *flags, *rpath, "-o", binary],
                           env=env, check=True, capture_output=True)
            for name, (target, kind) in LCF_FIXTURES.items():
                out = os.path.join(tmp, name)
                os.makedirs(out)
                subprocess.run([binary, out, target, kind], env=env, check=True, capture_output=True)
                for rel in LCF_BINARIES:
                    with self.subTest(fixture=name, file=rel):
                        self.assertEqual(sha256_file(os.path.join(out, rel)), sha256_file(os.path.join(FIXTURES, name, rel)))

    def test_wolf_map_round_trip(self):
        with open(os.path.join(FIXTURES, "wolf_character_min", "Data", "MapData", "SampleMap.mps"), "rb") as f:
            raw = f.read()
        header, body = decompress_mps(raw)
        parsed = parse_mps_body(body, version=header[0])
        self.assertEqual(len(parsed["events"]), 7)
        self.assertEqual(dump_mps_body(parsed, version=header[0]), body)
        self.assertEqual(decompress_mps(compress_mps(header, body)), (header, body))


if __name__ == "__main__":
    unittest.main()
