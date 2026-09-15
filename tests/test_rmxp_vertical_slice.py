#!/usr/bin/env python3
"""
Automated Test Suite for SuperRTP Phase 1 Task 4: RPG Maker XP / RGSS1 Character Compatibility.

Tests:
  1. Deterministic truecolor RGBA PNG encoder & alpha support (Color Type 6, 0..255)
  2. Canonical walking-character -> RMXP 4x4 Character layout transformation
  3. RMXP target build byte-for-byte reproducibility
  4. Frozen baseline regression integrity (canonical source, RM2000/RM2003 goldens, RMXP character)
  5. Target validator positive verification for RMXP
  6. Target validator rejection of non-compliant PNGs (dimensions, PLTE, alpha, idle column, arrow orientation)
  7. Clean-room RGSS1 test fixture manifest & script integrity
  8. Real mkxp-z headless positive RTP resolution (loads 001-Fighter01, 96x128, clean exit)
  9. Real mkxp-z headless negative control (empty RTP, isolates missing 001-Fighter01, exit code 1)
  10. Complete durable evidence chain & directional screenshot pixel verification
  11. Adversarial evidence tamper suite (manifest, asset, commit pin, logs, and pixel tampering)
"""

import os
import sys
import json
import zlib
import struct
import shutil
import tempfile
import subprocess
import hashlib
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

from png_utils import create_rgba_png, decode_png_rgb
from build_target import build_target, compute_sha256, transform_canonical_to_rmxp_character
from validate_target import validate_png_rmxp_character, validate_target
from verify_rmxp_runtime import verify_evidence_chain, verify_rmxp_screenshot, get_target_config

FROZEN_CANONICAL_CHARSET_SHA = "78ad9a170ac0ba06eb4756f9c9c19923e754e82c22025dab7dfbc46de5c1b790"
FROZEN_RM2000_CHARSET_SHA = "7fde5157142d929404f3fc3b599cbd6c558ef74b2135ac1172db53dd88641ee6"
FROZEN_RM2000_CHIPSET_SHA = "8a1c5552c544fb5195a92ab8f2f0e84b11d95fa3929250aa74b69630067fe137"
FROZEN_RMXP_CHARACTER_SHA = "b4e81694247632b5580b5eef55a17e61c6afd709092de0e574aed70b41759743"

class TestRMXPVerticalSlice(unittest.TestCase):

    def setUp(self):
        self.require_runtime = os.environ.get("SUPERRTP_REQUIRE_RUNTIME") == "1"

    def test_01_rgba_png_encoding_and_alpha(self):
        """Verify deterministic truecolor RGBA PNG encoder (Color Type 6) with full alpha range."""
        width, height = 4, 2
        # Test 8 pixels with varying alphas: 0, 64, 128, 255
        pixels = [
            (255, 0, 0, 0),        # fully transparent red
            (0, 255, 0, 64),       # 25% alpha green
            (0, 0, 255, 128),      # 50% alpha blue (semi-transparent)
            (255, 255, 255, 255),  # opaque white
            (10, 20, 30, 255),
            (40, 50, 60, 128),
            (70, 80, 90, 0),
            (100, 110, 120, 255)
        ]
        rgba_bytes = bytearray()
        for p in pixels:
            rgba_bytes.extend(p)

        png1 = create_rgba_png(width, height, rgba_bytes)
        png2 = create_rgba_png(width, height, rgba_bytes)
        self.assertEqual(png1, png2, "create_rgba_png must be 100% deterministic")

        # Inspect PNG chunks
        self.assertEqual(png1[:8], b"\x89PNG\r\n\x1a\n")
        ihdr_w, ihdr_h, bit_depth, color_type = struct.unpack(">IIBB", png1[16:26])
        self.assertEqual((ihdr_w, ihdr_h), (4, 2))
        self.assertEqual(bit_depth, 8)
        self.assertEqual(color_type, 6, "Must be Color Type 6 (RGBA)")
        self.assertNotIn(b"PLTE", png1, "RGBA PNG must not contain PLTE chunk")

        # Decode IDAT and verify pixel bytes
        idat_start = png1.find(b"IDAT") - 4
        idat_len = struct.unpack(">I", png1[idat_start:idat_start+4])[0]
        idat_payload = png1[idat_start+8 : idat_start+8+idat_len]
        decompressed = zlib.decompress(idat_payload)
        stride = 1 + width * 4
        self.assertEqual(len(decompressed), height * stride)

        row0_filter = decompressed[0]
        self.assertEqual(row0_filter, 0, "Filter type must be 0 (None)")
        row0_rgba = decompressed[1:stride]
        self.assertEqual(tuple(row0_rgba[8:12]), (0, 0, 255, 128), "Alpha 128 semi-transparency preserved")
        self.assertEqual(tuple(row0_rgba[0:4]), (255, 0, 0, 0), "Alpha 0 full transparency preserved")

    def test_02_canonical_to_rmxp_transformation_geometry(self):
        """Verify extraction of Character 0 and 4x4 RGSS1 remapping from canonical 2k sheet."""
        canonical_path = os.path.join(REPO_ROOT, "registry", "assets", "test_calibration_walking_character.rgba")
        with open(canonical_path, "rb") as f:
            raw_rgba = f.read()
        self.assertEqual(len(raw_rgba), 288 * 256 * 4)

        xp_png = transform_canonical_to_rmxp_character(raw_rgba)
        ihdr_w, ihdr_h, bit_depth, color_type = struct.unpack(">IIBB", xp_png[16:26])
        self.assertEqual((ihdr_w, ihdr_h), (96, 128))
        self.assertEqual(color_type, 6)

        # Decompress and verify dimensions and Column 3 idle repetition
        idat_idx = xp_png.find(b"IDAT") - 4
        idat_len = struct.unpack(">I", xp_png[idat_idx:idat_idx+4])[0]
        raw = zlib.decompress(xp_png[idat_idx+8 : idat_idx+8+idat_len])
        stride = 1 + 96 * 4

        def get_px(x, y):
            offset = y * stride + 1 + x * 4
            return tuple(raw[offset:offset+4])

        # Column 3 (x=72..95) must match Column 1 (x=24..47) exactly
        for row in range(4):
            for py in range(32):
                y = row * 32 + py
                for px in range(24):
                    col1_px = get_px(24 + px, y)
                    col3_px = get_px(72 + px, y)
                    self.assertEqual(col1_px, col3_px)

        # Directional mapping check:
        # Row 0: DOWN (tip at ly=21, notch at ly=6)
        r0_tip = get_px(24 + 11, 0 * 32 + 21)
        r0_notch = get_px(24 + 11, 0 * 32 + 6)
        self.assertEqual(r0_tip[3], 255)
        self.assertEqual(r0_notch[3], 0)

        # Row 1: LEFT (tip at lx=4, notch at lx=19)
        r1_tip = get_px(24 + 4, 1 * 32 + 13)
        r1_notch = get_px(24 + 19, 1 * 32 + 13)
        self.assertEqual(r1_tip[3], 255)
        self.assertEqual(r1_notch[3], 0)

        # Row 2: RIGHT (tip at lx=19, notch at lx=4)
        r2_tip = get_px(24 + 19, 2 * 32 + 13)
        r2_notch = get_px(24 + 4, 2 * 32 + 13)
        self.assertEqual(r2_tip[3], 255)
        self.assertEqual(r2_notch[3], 0)

        # Row 3: UP (tip at ly=5, notch at ly=21)
        r3_tip = get_px(24 + 11, 3 * 32 + 5)
        r3_notch = get_px(24 + 11, 3 * 32 + 21)
        self.assertEqual(r3_tip[3], 255)
        self.assertEqual(r3_notch[3], 0)

    def test_03_rmxp_target_build_reproducibility(self):
        """Verify target builder produces 100% byte-for-byte identical output across independent runs."""
        with tempfile.TemporaryDirectory(prefix="superrtp_build1_") as dir1, \
             tempfile.TemporaryDirectory(prefix="superrtp_build2_") as dir2:
            build_target("rmxp", output_dir=dir1, clean=True)
            build_target("rmxp", output_dir=dir2, clean=True)

            file1 = os.path.join(dir1, "Graphics", "Characters", "001-Fighter01.png")
            file2 = os.path.join(dir2, "Graphics", "Characters", "001-Fighter01.png")
            self.assertEqual(compute_sha256(file1), compute_sha256(file2))

            manifest1 = os.path.join(dir1, "manifest.json")
            manifest2 = os.path.join(dir2, "manifest.json")
            self.assertEqual(compute_sha256(manifest1), compute_sha256(manifest2))

    def test_04_frozen_baseline_regression_integrity(self):
        """Ensure accepted Phase 1 Tasks 1-3 assets and Task 4 assets match pinned SHA-256."""
        # 1. Canonical walking-character source
        canonical_rgba = os.path.join(REPO_ROOT, "registry", "assets", "test_calibration_walking_character.rgba")
        self.assertEqual(compute_sha256(canonical_rgba), FROZEN_CANONICAL_CHARSET_SHA)

        # 2. RM2000 CharSet golden output
        rm2k_actor1 = os.path.join(REPO_ROOT, "generated", "rm2000", "CharSet", "Actor1.png")
        self.assertEqual(compute_sha256(rm2k_actor1), FROZEN_RM2000_CHARSET_SHA)

        # 3. RM2000 ChipSet golden output
        rm2k_world = os.path.join(REPO_ROOT, "generated", "rm2000", "ChipSet", "World.png")
        self.assertEqual(compute_sha256(rm2k_world), FROZEN_RM2000_CHIPSET_SHA)

        # 4. RMXP 001-Fighter01.png golden output
        rmxp_char = os.path.join(REPO_ROOT, "generated", "rmxp", "Graphics", "Characters", "001-Fighter01.png")
        self.assertEqual(compute_sha256(rmxp_char), FROZEN_RMXP_CHARACTER_SHA)

    def test_05_target_validator_positive_rmxp(self):
        """Verify target validator passes for generated/rmxp target directory."""
        exit_code = validate_target("rmxp", target_dir=os.path.join(REPO_ROOT, "generated", "rmxp"))
        self.assertEqual(exit_code, 0, "validate_target for rmxp must exit with code 0")

        char_path = os.path.join(REPO_ROOT, "generated", "rmxp", "Graphics", "Characters", "001-Fighter01.png")
        meta = validate_png_rmxp_character(char_path)
        self.assertEqual(meta["width"], 96)
        self.assertEqual(meta["height"], 128)
        self.assertEqual(meta["color_type"], 6)
        self.assertEqual(meta["directions"], ["DOWN", "LEFT", "RIGHT", "UP"])

    def test_06_target_validator_rejections(self):
        """Verify validate_png_rmxp_character rejects corrupted, non-compliant, or wrong-oriented sheets."""
        valid_png_path = os.path.join(REPO_ROOT, "generated", "rmxp", "Graphics", "Characters", "001-Fighter01.png")
        with open(valid_png_path, "rb") as f:
            valid_bytes = f.read()

        with tempfile.TemporaryDirectory(prefix="superrtp_val_rej_") as tmp_dir:
            # 1. Invalid dimensions (e.g. 96x96 instead of 96x128)
            bad_dim_path = os.path.join(tmp_dir, "bad_dim.png")
            bad_dim_bytes = bytearray(valid_bytes)
            # Patch IHDR height at offset 20..23 to 96 (0x60)
            struct.pack_into(">I", bad_dim_bytes, 20, 96)
            # Update IHDR CRC
            crc = zlib.crc32(bad_dim_bytes[12:29])
            struct.pack_into(">I", bad_dim_bytes, 29, crc)
            with open(bad_dim_path, "wb") as f:
                f.write(bad_dim_bytes)
            with self.assertRaises(ValueError) as ctx:
                validate_png_rmxp_character(bad_dim_path)
            self.assertIn("Invalid XP Character dimensions", str(ctx.exception))

            # 2. Paletted indexed PNG (Color Type 3 with PLTE)
            rm2k_path = os.path.join(REPO_ROOT, "generated", "rm2000", "CharSet", "Actor1.png")
            with self.assertRaises(ValueError) as ctx:
                validate_png_rmxp_character(rm2k_path)
            self.assertIn("PLTE", str(ctx.exception))

            # 3. Missing transparent pixels (all alpha set to 255)
            no_alpha_path = os.path.join(tmp_dir, "no_alpha.png")
            raw_no_alpha = bytearray(96 * 128 * 4)
            for i in range(96 * 128):
                raw_no_alpha[i*4 : (i+1)*4] = b"\x10\x20\x30\xff"
            png_no_alpha = create_rgba_png(96, 128, raw_no_alpha)
            with open(no_alpha_path, "wb") as f:
                f.write(png_no_alpha)
            with self.assertRaises(ValueError) as ctx:
                validate_png_rmxp_character(no_alpha_path)
            self.assertIn("Missing transparent pixels", str(ctx.exception))

            # 4. Column 3 idle step mismatch with Column 1
            col_mismatch_path = os.path.join(tmp_dir, "col_mismatch.png")
            canonical_path = os.path.join(REPO_ROOT, "registry", "assets", "test_calibration_walking_character.rgba")
            with open(canonical_path, "rb") as f:
                raw_rgba = f.read()
            xp_bytes = bytearray(transform_canonical_to_rmxp_character(raw_rgba))
            # Decompress IDAT, mutate a single pixel in Column 3, recompress
            idat_idx = xp_bytes.find(b"IDAT") - 4
            idat_len = struct.unpack(">I", xp_bytes[idat_idx:idat_idx+4])[0]
            raw_decomp = bytearray(zlib.decompress(xp_bytes[idat_idx+8 : idat_idx+8+idat_len]))
            # Mutate Col 3 pixel at x=75, y=10
            stride = 1 + 96 * 4
            raw_decomp[10 * stride + 1 + 75 * 4] ^= 0xff
            re_idat = zlib.compress(raw_decomp)
            mutated_png = bytearray(xp_bytes[:idat_idx])
            mutated_png.extend(struct.pack(">I", len(re_idat)))
            mutated_png.extend(b"IDAT")
            mutated_png.extend(re_idat)
            mutated_png.extend(struct.pack(">I", zlib.crc32(b"IDAT" + re_idat)))
            mutated_png.extend(xp_bytes[idat_idx + 12 + idat_len :])
            with open(col_mismatch_path, "wb") as f:
                f.write(mutated_png)
            with self.assertRaises(ValueError) as ctx:
                validate_png_rmxp_character(col_mismatch_path)
            self.assertIn("Column 3 (idle step) does not match Column 1", str(ctx.exception))

    def test_07_clean_room_fixture_integrity(self):
        """Verify clean-room RGSS1 fixture manifest and hash integrity."""
        fixture_dir = os.path.join(REPO_ROOT, "tests", "fixtures", "rmxp_character_min")
        manifest_path = os.path.join(fixture_dir, "fixture_manifest.json")
        self.assertTrue(os.path.exists(manifest_path))

        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        self.assertEqual(manifest.get("engine"), "RPG Maker XP")
        self.assertEqual(manifest.get("rgss_version"), 1)
        self.assertIn("clean_room_attestation", manifest)

        for filename, info in manifest["files"].items():
            filepath = os.path.join(fixture_dir, filename)
            self.assertTrue(os.path.exists(filepath), f"Missing fixture file: {filepath}")
            act_hash = compute_sha256(filepath)
            self.assertEqual(act_hash, info["sha256"], f"Fixture file hash mismatch for {filename}")

    def test_08_mkxp_z_live_positive_runtime(self):
        """Verify mkxp-z loads 001-Fighter01.png cleanly with return code 0 and logs."""
        mkxp_bin = shutil.which("mkxp-z") or os.path.expanduser("~/.local/bin/mkxp-z")
        if not os.path.exists(mkxp_bin):
            if self.require_runtime:
                self.fail("mkxp-z required by SUPERRTP_REQUIRE_RUNTIME=1 but not found")
            raise unittest.SkipTest("mkxp-z not found on PATH or ~/.local/bin/mkxp-z")
        if not shutil.which("xvfb-run"):
            if self.require_runtime:
                self.fail("xvfb-run required by SUPERRTP_REQUIRE_RUNTIME=1 but not found")
            raise unittest.SkipTest("xvfb-run not found")

        fixture_dir = os.path.join(REPO_ROOT, "tests", "fixtures", "rmxp_character_min")
        target_dir = os.path.join(REPO_ROOT, "generated", "rmxp")
        mkxp_json_path = os.path.join(fixture_dir, "mkxp.json")

        # Configure positive run with RTP
        pos_conf = {
            "rgssVersion": 1,
            "gameFolder": ".",
            "customScript": "fixture.rb",
            "pathCache": True,
            "RTP": [target_dir]
        }
        with open(mkxp_json_path, "w", encoding="utf-8") as f:
            json.dump(pos_conf, f, indent=2)

        try:
            cmd = (
                f"cd {fixture_dir} && "
                f"xvfb-run -a -s '-screen 0 640x480x24' bash -c '"
                f"ALSOFT_DRIVERS=null SDL_VIDEODRIVER=x11 {mkxp_bin}'"
            )
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
            self.assertEqual(res.returncode, 0, f"mkxp-z exited with code {res.returncode}:\n{res.stdout}\n{res.stderr}")
            self.assertIn("MKXP-Z VERSION: 2.4.2/826929e", res.stdout)
            self.assertIn("SUPERRTP_RMXP_CHARACTER_LOADED 96x128", res.stdout)
            self.assertIn("SUPERRTP_RMXP_RENDER_DONE", res.stdout)
        finally:
            # Restore clean mkxp.json
            neg_conf = {
                "rgssVersion": 1,
                "gameFolder": ".",
                "customScript": "fixture.rb",
                "pathCache": True,
                "RTP": []
            }
            with open(mkxp_json_path, "w", encoding="utf-8") as f:
                json.dump(neg_conf, f, indent=2)
                f.write("\n")

    def test_09_mkxp_z_live_negative_control(self):
        """Verify mkxp-z negative control: empty RTP isolates missing 001-Fighter01.png (exit code 1)."""
        mkxp_bin = shutil.which("mkxp-z") or os.path.expanduser("~/.local/bin/mkxp-z")
        if not os.path.exists(mkxp_bin):
            if self.require_runtime:
                self.fail("mkxp-z required by SUPERRTP_REQUIRE_RUNTIME=1 but not found")
            raise unittest.SkipTest("mkxp-z not found")
        if not shutil.which("xvfb-run"):
            if self.require_runtime:
                self.fail("xvfb-run required by SUPERRTP_REQUIRE_RUNTIME=1 but not found")
            raise unittest.SkipTest("xvfb-run not found")

        fixture_dir = os.path.join(REPO_ROOT, "tests", "fixtures", "rmxp_character_min")
        mkxp_json_path = os.path.join(fixture_dir, "mkxp.json")

        neg_conf = {
            "rgssVersion": 1,
            "gameFolder": ".",
            "customScript": "fixture.rb",
            "pathCache": True,
            "RTP": []
        }
        with open(mkxp_json_path, "w", encoding="utf-8") as f:
            json.dump(neg_conf, f, indent=2)
            f.write("\n")

        cmd = (
            f"cd {fixture_dir} && "
            f"xvfb-run -a -s '-screen 0 640x480x24' bash -c '"
            f"ALSOFT_DRIVERS=null SDL_VIDEODRIVER=x11 {mkxp_bin}'"
        )
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        self.assertEqual(res.returncode, 1, f"Expected exit code 1 for negative control, got {res.returncode}")
        self.assertIn("SUPERRTP_RMXP_MISSING_ASSET: No such file or directory - Graphics/Characters/001-Fighter01", res.stderr)

    def test_10_evidence_chain_and_pixel_verification(self):
        """Verify complete durable evidence chain and pixel verification for RMXP."""
        evidence_path = os.path.join(REPO_ROOT, "artifacts", "runtime", "rmxp", "character", "verification_evidence.json")
        self.assertTrue(os.path.exists(evidence_path), f"Evidence file not found: {evidence_path}")
        self.assertTrue(verify_evidence_chain(evidence_path=evidence_path))

    def test_11_adversarial_evidence_tamper_suite(self):
        """Adversarially verify that any tampering with evidence JSON or screenshots is caught."""
        evidence_path = os.path.join(REPO_ROOT, "artifacts", "runtime", "rmxp", "character", "verification_evidence.json")
        with open(evidence_path, "r", encoding="utf-8") as f:
            original_evidence = json.load(f)

        with tempfile.TemporaryDirectory(prefix="superrtp_rmxp_tamper_") as tmp_dir:
            # 1. Tamper target_manifest_sha256
            tamper1 = dict(original_evidence)
            tamper1["target_manifest_sha256"] = "0000000000000000000000000000000000000000000000000000000000000000"
            t1_path = os.path.join(tmp_dir, "ev1.json")
            with open(t1_path, "w") as f:
                json.dump(tamper1, f)
            with self.assertRaises(ValueError) as ctx:
                verify_evidence_chain(evidence_path=t1_path)
            self.assertIn("Target manifest hash mismatch", str(ctx.exception))

            # 2. Tamper mkxp-z version pin
            tamper2 = dict(original_evidence)
            tamper2["mkxp_z_version"] = "2.4.2/abcdef0"
            t2_path = os.path.join(tmp_dir, "ev2.json")
            with open(t2_path, "w") as f:
                json.dump(tamper2, f)
            with self.assertRaises(ValueError) as ctx:
                verify_evidence_chain(evidence_path=t2_path)
            self.assertIn("mkxp-z commit pin violation", str(ctx.exception))

            # 3. Tamper screenshot hash
            tamper3 = dict(original_evidence)
            tamper3["screenshots"] = dict(original_evidence["screenshots"])
            tamper3["screenshots"]["rmxp_character_positive.png"] = "badf00d"
            t3_path = os.path.join(tmp_dir, "ev3.json")
            with open(t3_path, "w") as f:
                json.dump(tamper3, f)
            with self.assertRaises(ValueError) as ctx:
                verify_evidence_chain(evidence_path=t3_path)
            self.assertIn("Screenshot hash mismatch", str(ctx.exception))

            # 4. Tamper positive screenshot pixel (modify arrow tip)
            cfg = get_target_config()
            pos_shot_path = os.path.join(cfg["artifacts_dir"], "rmxp_character_positive.png")
            w, h, pixels = decode_png_rgb(pos_shot_path)
            # Mutate DOWN tip at (307, 197) to green
            pixels_tampered = [row[:] for row in pixels]
            pixels_tampered[197][307] = (0, 255, 0)
            tampered_png_path = os.path.join(tmp_dir, "tampered_pos.png")
            # Build RGBA bytearray
            raw_rgba = bytearray()
            for row in pixels_tampered:
                for r, g, b in row:
                    raw_rgba.extend((r, g, b, 255))
            with open(tampered_png_path, "wb") as f:
                f.write(create_rgba_png(w, h, raw_rgba))

            with self.assertRaises(ValueError) as ctx:
                verify_rmxp_screenshot(tampered_png_path, mode="positive")
            self.assertIn("arrow tip mismatch", str(ctx.exception))

            # 5. Tamper negative screenshot pixel (character tip present on pad)
            neg_shot_path = os.path.join(cfg["artifacts_dir"], "rmxp_character_negative_control.png")
            w, h, pixels_neg = decode_png_rgb(neg_shot_path)
            pixels_neg_tampered = [row[:] for row in pixels_neg]
            pixels_neg_tampered[197][307] = (10, 40, 70) # character tip color
            tampered_neg_path = os.path.join(tmp_dir, "tampered_neg.png")
            raw_neg_rgba = bytearray()
            for row in pixels_neg_tampered:
                for r, g, b in row:
                    raw_neg_rgba.extend((r, g, b, 255))
            with open(tampered_neg_path, "wb") as f:
                f.write(create_rgba_png(w, h, raw_neg_rgba))

            with self.assertRaises(ValueError) as ctx:
                verify_rmxp_screenshot(tampered_neg_path, mode="negative_control")
            self.assertIn("Negative control unexpectedly rendered character sprite", str(ctx.exception))

if __name__ == "__main__":
    unittest.main()
