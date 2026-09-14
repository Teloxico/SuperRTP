#!/usr/bin/env python3
"""
Automated Test Suite for SuperRTP Phase 1 Vertical Slice.

Tests:
  1. Canonical asset generation & deterministic reproducibility
  2. PNG structure & RM2000 CharSet compliance (288x256, 8-bit indexed, index 0 transparent)
  3. Provenance completeness & clean-room invariant attestations
  4. Target builder & manifest generation
  5. Target validator positive verification & rejection of corrupted/invalid assets
  6. Real EasyRPG Player headless RTP resolution (positive control)
  7. Real EasyRPG Player missing-asset fallback (negative control)
"""

import os
import sys
import json
import shutil
import tempfile
import subprocess
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

from generate_calibration_charset import generate_calibration_charset, create_png
from build_target import build_target, compute_sha256
from validate_target import validate_png_charset, validate_provenance, validate_target

class TestSuperRTPVerticalSlice(unittest.TestCase):

    def test_01_canonical_asset_reproducibility(self):
        """Verify canonical asset is 100% byte-for-byte deterministic."""
        png1 = generate_calibration_charset()
        png2 = generate_calibration_charset()
        self.assertEqual(png1, png2, "Generator must be byte-for-byte deterministic")

        canonical_path = os.path.join(REPO_ROOT, "registry", "assets", "test_calibration_walking_character.png")
        self.assertTrue(os.path.exists(canonical_path), f"Canonical asset not found at {canonical_path}")

        actual_sha256 = compute_sha256(canonical_path)
        with open(os.path.join(REPO_ROOT, "registry", "assets", "test_calibration_walking_character.json"), "r") as f:
            meta = json.load(f)
        self.assertEqual(actual_sha256, meta["sha256"], "Canonical asset hash must match metadata")

    def test_02_png_structural_compliance(self):
        """Verify PNG conforms to strict RM2000 CharSet specification."""
        canonical_path = os.path.join(REPO_ROOT, "registry", "assets", "test_calibration_walking_character.png")
        specs = validate_png_charset(canonical_path)

        self.assertEqual(specs["width"], 288)
        self.assertEqual(specs["height"], 256)
        self.assertEqual(specs["bit_depth"], 8)
        self.assertEqual(specs["color_type"], 3)  # Indexed color
        self.assertLessEqual(specs["num_colors"], 256)
        self.assertEqual(specs["transparent_index"], 0)
        self.assertEqual(specs["characters_grid"], "4x2")
        self.assertEqual(specs["frame_cell"], "24x32")

    def test_03_clean_room_provenance_attestation(self):
        """Verify clean-room attestations and license metadata."""
        canonical_path = os.path.join(REPO_ROOT, "registry", "assets", "test_calibration_walking_character.png")
        sha256 = compute_sha256(canonical_path)
        prov = validate_provenance(REPO_ROOT, "test.calibration.walking-character", sha256)

        att = prov["clean_room_attestation"]
        self.assertFalse(att["proprietary_rtp_derived"])
        self.assertFalse(att["openrtp_derived"])
        self.assertFalse(att["external_art_used"])
        self.assertFalse(att["ai_generation_used"])
        self.assertTrue(att["geometric_primitives_only"])
        self.assertEqual(prov["license"], "CC0-1.0")
        self.assertTrue(prov["test_only"])

    def test_04_target_builder(self):
        """Verify target builder produces expected output and manifest."""
        temp_dir = tempfile.mkdtemp(prefix="superrtp_build_test_")
        try:
            build_target("rm2000", output_dir=temp_dir, clean=True)
            manifest_path = os.path.join(temp_dir, "manifest.json")
            self.assertTrue(os.path.exists(manifest_path))

            with open(manifest_path, "r") as f:
                manifest = json.load(f)

            entries = {e["slot"]: e for e in manifest["entries"]}
            self.assertIn("CharSet/Actor1.png", entries)
            self.assertIn("CharSet/Hero1.png", entries)
            self.assertTrue(entries["CharSet/Actor1.png"]["is_primary"])
            self.assertFalse(entries["CharSet/Hero1.png"]["is_primary"])

            # Verify files exist on disk
            primary_file = os.path.join(temp_dir, "CharSet", "Actor1.png")
            alias_file = os.path.join(temp_dir, "CharSet", "Hero1.png")
            self.assertTrue(os.path.exists(primary_file))
            self.assertTrue(os.path.exists(alias_file))

            # Validate target with validator
            exit_code = validate_target("rm2000", target_dir=temp_dir)
            self.assertEqual(exit_code, 0)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

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

    def test_06_easyrpg_rtp_positive_control(self):
        """Verify real EasyRPG Player resolves Actor1 from SuperRTP target pack."""
        player_bin = shutil.which("easyrpg-player")
        if not player_bin:
            self.skipTest("easyrpg-player not found on PATH")

        fixture_dir = os.path.join(REPO_ROOT, "tests", "fixtures", "rm2000_min")
        rtp_dir = os.path.join(REPO_ROOT, "generated", "rm2000")

        # Ensure target pack is built
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

        # Check RTP was recognized
        self.assertIn("Adding", output)
        self.assertIn("to RTP path", output)
        self.assertIn('RTP is "Official English"', output)

        # Crucially: verify Actor1 was NOT reported missing
        self.assertNotIn("Image not found: CharSet/Actor1", output)

    def test_07_easyrpg_negative_control(self):
        """Verify real EasyRPG Player fails to find Actor1 when RTP is disabled."""
        player_bin = shutil.which("easyrpg-player")
        if not player_bin:
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

if __name__ == "__main__":
    unittest.main(verbosity=2)
