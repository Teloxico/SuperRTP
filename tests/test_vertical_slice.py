#!/usr/bin/env python3
"""
Automated Test Suite for SuperRTP Phase 1 Vertical Slice.

Tests:
  1. Canonical asset generation & deterministic reproducibility (raw RGBA + preview)
  2. PNG structure & RM2000 CharSet compliance (288x256, 8-bit indexed, index 0 transparent)
  3. Clean-room provenance attestation & generalized schema adherence
  4. Target builder, byte-for-byte reproducibility across runs, and slot alias correctness
  5. Target validator positive verification & rejection of corrupted/invalid assets
  6. Schema validation using schema_validator (assets & provenance)
  7. Clean-room fixture manifest hash verification
  8. Real EasyRPG Player headless RTP resolution (positive control, clean logs)
  9. Real EasyRPG Player missing-asset fallback (negative control, exact failure isolation)
  10. Four-direction runtime verification artifacts presence & geometry
"""

import os
import sys
import json
import shutil
import tempfile
import subprocess
import hashlib
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

from generate_calibration_charset import generate_calibration_charset
from build_target import build_target, compute_sha256, create_indexed_png as create_png
from validate_target import validate_png_charset, validate_provenance, validate_target
from schema_validator import validate_schema

class TestSuperRTPVerticalSlice(unittest.TestCase):

    def test_01_canonical_asset_reproducibility(self):
        """Verify canonical master RGBA and PNG preview are 100% byte-for-byte deterministic."""
        raw1, png1 = generate_calibration_charset()
        raw2, png2 = generate_calibration_charset()
        self.assertEqual(raw1, raw2, "Raw RGBA generator must be byte-for-byte deterministic")
        self.assertEqual(png1, png2, "Master preview generator must be byte-for-byte deterministic")

        rgba_path = os.path.join(REPO_ROOT, "registry", "assets", "test_calibration_walking_character.rgba")
        self.assertTrue(os.path.exists(rgba_path), f"Canonical raw RGBA not found at {rgba_path}")
        self.assertEqual(compute_sha256(rgba_path), hashlib.sha256(raw1).hexdigest())

        with open(os.path.join(REPO_ROOT, "registry", "assets", "test_calibration_walking_character.json"), "r") as f:
            meta = json.load(f)
        self.assertEqual(meta["sha256"], compute_sha256(rgba_path))

    def test_02_png_structural_compliance(self):
        """Verify built target PNG conforms to strict RM2000 CharSet specification."""
        # Ensure target pack is built
        rtp_dir = os.path.join(REPO_ROOT, "generated", "rm2000")
        target_png = os.path.join(rtp_dir, "CharSet", "Actor1.png")
        if not os.path.exists(target_png):
            build_target("rm2000", output_dir=rtp_dir, clean=True)

        specs = validate_png_charset(target_png)
        self.assertEqual(specs["width"], 288)
        self.assertEqual(specs["height"], 256)
        self.assertEqual(specs["bit_depth"], 8)
        self.assertEqual(specs["color_type"], 3)  # Indexed color
        self.assertLessEqual(specs["num_colors"], 256)
        self.assertEqual(specs["transparent_index"], 0)
        self.assertEqual(specs["characters_grid"], "4x2")
        self.assertEqual(specs["frame_cell"], "24x32")

    def test_03_clean_room_provenance_attestation(self):
        """Verify clean-room attestations and license metadata under generalized provenance schema."""
        rgba_path = os.path.join(REPO_ROOT, "registry", "assets", "test_calibration_walking_character.rgba")
        sha256 = compute_sha256(rgba_path)
        prov = validate_provenance(REPO_ROOT, "test.calibration.walking-character", sha256)

        self.assertEqual(prov["source_type"], "project_synthetic")
        att = prov["clean_room_attestation"]
        self.assertFalse(att["proprietary_rtp_derived"])
        self.assertFalse(att["openrtp_derived"])
        self.assertEqual(prov["license"], "CC0-1.0")
        self.assertTrue(prov["test_only"])

    def test_04_target_builder_and_byte_reproducibility(self):
        """Verify target builder produces byte-identical outputs across runs and correct RM2000 slots."""
        temp_dir1 = tempfile.mkdtemp(prefix="superrtp_build1_")
        temp_dir2 = tempfile.mkdtemp(prefix="superrtp_build2_")
        try:
            # Build twice with static timestamp (SOURCE_DATE_EPOCH=0)
            build_target("rm2000", output_dir=temp_dir1, clean=True, timestamp=0)
            build_target("rm2000", output_dir=temp_dir2, clean=True, timestamp=0)

            # Compare all files
            for root, _, files in os.walk(temp_dir1):
                rel_dir = os.path.relpath(root, temp_dir1)
                for f in files:
                    p1 = os.path.join(root, f)
                    p2 = os.path.join(temp_dir2, rel_dir, f)
                    self.assertTrue(os.path.exists(p2), f"Missing file in second build: {f}")
                    self.assertEqual(compute_sha256(p1), compute_sha256(p2), f"Build divergence in {f}")

            manifest_path = os.path.join(temp_dir1, "manifest.json")
            with open(manifest_path, "r") as f:
                manifest = json.load(f)

            entries = {e["slot"]: e for e in manifest["entries"]}
            # Primary slot
            self.assertIn("CharSet/Actor1.png", entries)
            self.assertTrue(entries["CharSet/Actor1.png"]["is_primary"])
            # RM2000 must NOT contain RM2003 aliases like Hero1
            self.assertNotIn("CharSet/Hero1.png", entries)

            # Validate target with validator
            exit_code = validate_target("rm2000", target_dir=temp_dir1)
            self.assertEqual(exit_code, 0)
        finally:
            shutil.rmtree(temp_dir1, ignore_errors=True)
            shutil.rmtree(temp_dir2, ignore_errors=True)

    def test_05_validator_rejection_of_invalid_assets(self):
        """Verify validator aggressively rejects non-compliant assets."""
        # Case A: Wrong dimensions (e.g. 100x100 instead of 288x256)
        bad_png = create_png(100, 100, [(0,0,0), (255,255,255)], bytearray(100 * 100))
        temp_bad = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        try:
            temp_bad.write(bad_png)
            temp_bad.close()
            with self.assertRaises(ValueError) as ctx:
                validate_png_charset(temp_bad.name)
            self.assertIn("288x256", str(ctx.exception))
        finally:
            os.unlink(temp_bad.name)

        # Case B: Corrupted signature
        temp_bad = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        try:
            temp_bad.write(b"NOT A PNG")
            temp_bad.close()
            with self.assertRaises(ValueError) as ctx:
                validate_png_charset(temp_bad.name)
            self.assertIn("signature", str(ctx.exception).lower())
        finally:
            os.unlink(temp_bad.name)

    def test_06_schema_validation(self):
        """Verify JSON schemas and registry instances validate cleanly."""
        asset_schema_path = os.path.join(REPO_ROOT, "schemas", "asset.schema.json")
        prov_schema_path = os.path.join(REPO_ROOT, "schemas", "provenance.schema.json")

        with open(asset_schema_path, "r") as f:
            asset_schema = json.load(f)
        with open(prov_schema_path, "r") as f:
            prov_schema = json.load(f)

        asset_inst_path = os.path.join(REPO_ROOT, "registry", "assets", "test_calibration_walking_character.json")
        prov_inst_path = os.path.join(REPO_ROOT, "registry", "provenance", "test_calibration_walking_character.json")

        with open(asset_inst_path, "r") as f:
            asset_inst = json.load(f)
        with open(prov_inst_path, "r") as f:
            prov_inst = json.load(f)

        # Valid instances must pass
        validate_schema(asset_inst, asset_schema)
        validate_schema(prov_inst, prov_schema)

        # Invalid provenance instance must fail
        bad_prov = json.loads(json.dumps(prov_inst))
        bad_prov["clean_room_attestation"]["proprietary_rtp_derived"] = True
        with self.assertRaises(ValueError):
            validate_schema(bad_prov, prov_schema)

    def test_07_clean_room_fixture_manifest_integrity(self):
        """Verify clean-room test fixture binaries and source match fixture_manifest.json."""
        manifest_path = os.path.join(REPO_ROOT, "tests", "fixtures", "rm2000_min", "fixture_manifest.json")
        self.assertTrue(os.path.exists(manifest_path), "Fixture manifest must exist")
        with open(manifest_path, "r") as f:
            manifest = json.load(f)

        fixture_dir = os.path.dirname(manifest_path)
        # Check source generator
        gen_cpp_path = os.path.join(REPO_ROOT, manifest["generator_source"])
        self.assertEqual(compute_sha256(gen_cpp_path), manifest["generator_sha256"], "Generator source modified")

        # Check each fixture file
        for rel_file, expected_hash in manifest["files"].items():
            full_path = os.path.join(fixture_dir, rel_file)
            self.assertTrue(os.path.exists(full_path), f"Missing fixture file: {rel_file}")
            self.assertEqual(compute_sha256(full_path), expected_hash, f"Hash mismatch for fixture {rel_file}")

    def test_08_easyrpg_rtp_positive_control(self):
        """Verify real EasyRPG Player resolves Actor1 from SuperRTP target pack with zero missing asset warnings."""
        player_bin = shutil.which("easyrpg-player")
        require_runtime = os.environ.get("SUPERRTP_REQUIRE_RUNTIME") == "1"

        if not player_bin:
            if require_runtime:
                self.fail("easyrpg-player is required by SUPERRTP_REQUIRE_RUNTIME=1 but was not found on PATH")
            self.skipTest("easyrpg-player not found on PATH")

        fixture_dir = os.path.join(REPO_ROOT, "tests", "fixtures", "rm2000_min")
        rtp_dir = os.path.join(REPO_ROOT, "generated", "rm2000")

        if not os.path.exists(os.path.join(rtp_dir, "CharSet", "Actor1.png")):
            build_target("rm2000", output_dir=rtp_dir, clean=True)

        env = os.environ.copy()
        env["SDL_VIDEODRIVER"] = "dummy"
        env["SDL_AUDIODRIVER"] = "dummy"

        cmd = [
            player_bin,
            "--project-path", fixture_dir,
            "--rtp-path", rtp_dir,
            "--engine", "rpg2k",
            "--new-game",
            "--disable-audio",
            "--no-pause-focus-lost",
            "--no-log-color"
        ]

        try:
            res = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=3.5)
            output = res.stdout + res.stderr
        except subprocess.TimeoutExpired as e:
            out = (e.stdout or b'').decode('utf-8', errors='replace') if isinstance(e.stdout, bytes) else (e.stdout or '')
            err = (e.stderr or b'').decode('utf-8', errors='replace') if isinstance(e.stderr, bytes) else (e.stderr or '')
            output = out + err

        # RTP recognized
        self.assertIn("Adding", output)
        self.assertIn("to RTP path", output)
        self.assertIn('RTP is "Official English"', output)

        # Actor1 resolved from RTP
        self.assertNotIn("Image not found: CharSet/Actor1", output)
        # Bundled clean-room fixture assets resolved
        self.assertNotIn("Image not found: ChipSet", output)
        self.assertNotIn("Image not found: System", output)

    def test_09_easyrpg_negative_control(self):
        """Verify real EasyRPG Player fails cleanly on Actor1 when RTP is disabled."""
        player_bin = shutil.which("easyrpg-player")
        require_runtime = os.environ.get("SUPERRTP_REQUIRE_RUNTIME") == "1"

        if not player_bin:
            if require_runtime:
                self.fail("easyrpg-player is required by SUPERRTP_REQUIRE_RUNTIME=1 but was not found on PATH")
            self.skipTest("easyrpg-player not found on PATH")

        fixture_dir = os.path.join(REPO_ROOT, "tests", "fixtures", "rm2000_min")

        env = os.environ.copy()
        env["SDL_VIDEODRIVER"] = "dummy"
        env["SDL_AUDIODRIVER"] = "dummy"

        cmd = [
            player_bin,
            "--project-path", fixture_dir,
            "--no-rtp",
            "--engine", "rpg2k",
            "--new-game",
            "--disable-audio",
            "--no-pause-focus-lost",
            "--no-log-color"
        ]

        try:
            res = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=3.5)
            output = res.stdout + res.stderr
        except subprocess.TimeoutExpired as e:
            out = (e.stdout or b'').decode('utf-8', errors='replace') if isinstance(e.stdout, bytes) else (e.stdout or '')
            err = (e.stderr or b'').decode('utf-8', errors='replace') if isinstance(e.stderr, bytes) else (e.stderr or '')
            output = out + err

        self.assertIn("RTP support is disabled", output)
        self.assertIn("Image not found: CharSet/Actor1", output)
        # Confirm no other assets failed (clean negative control isolation)
        self.assertNotIn("Image not found: ChipSet", output)
        self.assertNotIn("Image not found: System", output)

    def test_10_directional_runtime_artifacts(self):
        """Verify all 4 directional runtime verification screenshots and negative control exist with proper geometry."""
        artifact_dir = os.path.join(REPO_ROOT, "artifacts", "runtime", "rm2000", "charset")
        required_artifacts = [
            "rm2000_charset_down.png",
            "rm2000_charset_left.png",
            "rm2000_charset_up.png",
            "rm2000_charset_right.png",
            "rm2000_charset_negative_control.png"
        ]
        for name in required_artifacts:
            path = os.path.join(artifact_dir, name)
            self.assertTrue(os.path.exists(path), f"Missing runtime verification artifact: {name}")
            with open(path, "rb") as f:
                header = f.read(24)
            # PNG signature
            self.assertEqual(header[:8], b"\x89PNG\r\n\x1a\n")
            # Width and height in IHDR (bytes 16..24)
            w = int.from_bytes(header[16:20], "big")
            h = int.from_bytes(header[20:24], "big")
            self.assertEqual((w, h), (640, 480), f"Unexpected screenshot dimensions for {name}: {w}x{h}")

if __name__ == "__main__":
    unittest.main(verbosity=2)
