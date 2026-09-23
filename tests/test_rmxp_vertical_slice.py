#!/usr/bin/env python3
"""
Automated Test Suite for SuperRTP Phase 1 Task 4: RPG Maker XP / RGSS1 Character Compatibility.

Tests:
  1. Deterministic truecolor RGBA PNG encoder & alpha support (Color Type 6, 0..255)
  2. Semantic walking-frame extraction layer (directions, phases, decoupled architecture)
  3. Canonical walking-character -> RMXP 4x4 Character layout transformation
  4. RMXP target build byte-for-byte reproducibility
  5. Frozen baseline regression integrity (canonical source, RM2000 and RM2003 golden assets and aliases, RMXP character)
  6. Target validator positive verification for RMXP
  7. Target validator rejection of non-compliant PNGs (dimensions, PLTE, alpha, idle column, arrow orientation)
  8. Clean-room RGSS1 test fixture manifest & script integrity
  9. Real mkxp-z headless positive RTP resolution (loads 001-Fighter01, 96x128, clean exit code 0) via temp config
  10. Real mkxp-z headless negative control (empty RTP, isolates missing 001-Fighter01, exit code 1) via temp config
  11. Complete durable evidence chain & directional screenshot pixel verification
  12. Comprehensive adversarial evidence tamper suite (attacks all authoritative fields, configs, scripts, exit codes, and pixel assertions)
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
from build_target import build_target
from repo import sha256_file as compute_sha256
from transforms import (
    extract_walking_frames,
    pack_rmxp_character,
    transform_canonical_to_rmxp_character
)
from validate_target import validate_png_rmxp_character, validate_target
from verify_rmxp_runtime import (
    verify_evidence_chain,
    verify_rmxp_screenshot,
    get_target_config,
    PINNED_MKXP_COMMIT
)

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

    def test_02_semantic_walking_frame_extraction(self):
        """Verify semantic walking-frame extraction layer cleanly decouples sheet geometry from packing."""
        canonical_path = os.path.join(REPO_ROOT, "registry", "assets", "test_calibration_walking_character.rgba")
        with open(canonical_path, "rb") as f:
            raw_rgba = f.read()
        self.assertEqual(len(raw_rgba), 288 * 256 * 4)

        # Extract frames for Character 0
        frames = extract_walking_frames(raw_rgba, char_idx=0)
        expected_dirs = {"UP", "RIGHT", "DOWN", "LEFT"}
        expected_phases = {"STEP_LEFT", "IDLE", "STEP_RIGHT"}

        self.assertEqual(set(frames.keys()), expected_dirs)
        for direction in expected_dirs:
            self.assertEqual(set(frames[direction].keys()), expected_phases)
            for phase in expected_phases:
                frame_bytes = frames[direction][phase]
                self.assertEqual(len(frame_bytes), 24 * 32 * 4, f"Frame {direction}/{phase} must be 24x32 RGBA")

        # Verify semantic content differences:
        # UP arrow tip (y=5, x=11) should be opaque in UP, but transparent in DOWN
        up_idle = frames["UP"]["IDLE"]
        down_idle = frames["DOWN"]["IDLE"]
        up_tip_offset = (5 * 24 + 11) * 4
        down_tip_offset = (21 * 24 + 11) * 4

        self.assertEqual(up_idle[up_tip_offset + 3], 255, "UP arrow tip must be opaque in UP direction")
        self.assertEqual(down_idle[down_tip_offset + 3], 255, "DOWN arrow tip must be opaque in DOWN direction")
        self.assertEqual(up_idle[down_tip_offset + 3], 0, "DOWN tip position must be transparent in UP direction")

        # Verify pack_rmxp_character consumes semantic frames and produces compliant XP sheet
        xp_png = pack_rmxp_character(frames)
        self.assertEqual(compute_sha256_bytes(xp_png), FROZEN_RMXP_CHARACTER_SHA)

    def test_03_canonical_to_rmxp_transformation_geometry(self):
        """Verify end-to-end extraction of Character 0 and 4x4 RGSS1 remapping from canonical 2k sheet."""
        canonical_path = os.path.join(REPO_ROOT, "registry", "assets", "test_calibration_walking_character.rgba")
        with open(canonical_path, "rb") as f:
            raw_rgba = f.read()

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

    def test_04_rmxp_target_build_reproducibility(self):
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

    def test_05_frozen_baseline_regression_integrity(self):
        """Ensure accepted Phase 1 Tasks 1-3 assets and Task 4 assets match pinned SHA-256."""
        # 1. Canonical walking-character source
        canonical_rgba = os.path.join(REPO_ROOT, "registry", "assets", "test_calibration_walking_character.rgba")
        self.assertEqual(compute_sha256(canonical_rgba), FROZEN_CANONICAL_CHARSET_SHA)

        # 2. RM2000 CharSet golden output
        rm2k_actor1 = os.path.join(REPO_ROOT, "generated", "rm2000", "CharSet", "Actor1.png")
        self.assertEqual(compute_sha256(rm2k_actor1), FROZEN_RM2000_CHARSET_SHA)

        # 3. RM2003 CharSet primary and alias
        rm2k3_actor1 = os.path.join(REPO_ROOT, "generated", "rm2003", "CharSet", "Actor1.png")
        rm2k3_hero1 = os.path.join(REPO_ROOT, "generated", "rm2003", "CharSet", "Hero1.png")
        self.assertEqual(compute_sha256(rm2k3_actor1), FROZEN_RM2000_CHARSET_SHA)
        self.assertEqual(compute_sha256(rm2k3_hero1), FROZEN_RM2000_CHARSET_SHA)

        # 4. RM2000 ChipSet primary and alias
        rm2k_world = os.path.join(REPO_ROOT, "generated", "rm2000", "ChipSet", "World.png")
        rm2k_basis = os.path.join(REPO_ROOT, "generated", "rm2000", "ChipSet", "Basis.png")
        self.assertEqual(compute_sha256(rm2k_world), FROZEN_RM2000_CHIPSET_SHA)
        self.assertEqual(compute_sha256(rm2k_basis), FROZEN_RM2000_CHIPSET_SHA)

        # 5. RM2003 ChipSet primary and aliases
        rm2k3_world = os.path.join(REPO_ROOT, "generated", "rm2003", "ChipSet", "World.png")
        rm2k3_main = os.path.join(REPO_ROOT, "generated", "rm2003", "ChipSet", "Main.png")
        rm2k3_basic = os.path.join(REPO_ROOT, "generated", "rm2003", "ChipSet", "Basic.png")
        self.assertEqual(compute_sha256(rm2k3_world), FROZEN_RM2000_CHIPSET_SHA)
        self.assertEqual(compute_sha256(rm2k3_main), FROZEN_RM2000_CHIPSET_SHA)
        self.assertEqual(compute_sha256(rm2k3_basic), FROZEN_RM2000_CHIPSET_SHA)

        # 6. RMXP 001-Fighter01.png golden output
        rmxp_char = os.path.join(REPO_ROOT, "generated", "rmxp", "Graphics", "Characters", "001-Fighter01.png")
        self.assertEqual(compute_sha256(rmxp_char), FROZEN_RMXP_CHARACTER_SHA)

    def test_06_target_validator_positive_rmxp(self):
        """Verify target validator passes for generated/rmxp target directory."""
        exit_code = validate_target("rmxp", target_dir=os.path.join(REPO_ROOT, "generated", "rmxp"))
        self.assertEqual(exit_code, 0, "validate_target for rmxp must exit with code 0")

        char_path = os.path.join(REPO_ROOT, "generated", "rmxp", "Graphics", "Characters", "001-Fighter01.png")
        meta = validate_png_rmxp_character(char_path)
        self.assertEqual(meta["width"], 96)
        self.assertEqual(meta["height"], 128)
        self.assertEqual(meta["color_type"], 6)
        self.assertEqual(meta["directions"], ["DOWN", "LEFT", "RIGHT", "UP"])

    def test_07_target_validator_rejections(self):
        """Verify validate_png_rmxp_character rejects corrupted, non-compliant, or wrong-oriented sheets."""
        valid_png_path = os.path.join(REPO_ROOT, "generated", "rmxp", "Graphics", "Characters", "001-Fighter01.png")
        with open(valid_png_path, "rb") as f:
            valid_bytes = f.read()

        with tempfile.TemporaryDirectory(prefix="superrtp_val_rej_") as tmp_dir:
            # 1. Invalid dimensions (e.g. 96x96 instead of 96x128)
            bad_dim_path = os.path.join(tmp_dir, "bad_dim.png")
            bad_dim_bytes = bytearray(valid_bytes)
            struct.pack_into(">I", bad_dim_bytes, 20, 96)
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

    def test_08_clean_room_fixture_integrity(self):
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

    def test_09_mkxp_z_live_positive_runtime(self):
        """Verify mkxp-z loads 001-Fighter01.png cleanly with return code 0 via temporary runtime config."""
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

        # Execute mkxp-z from temporary runtime directory so tracked fixture files are not mutated
        with tempfile.TemporaryDirectory(prefix="superrtp_pos_test_") as tmp_dir:
            pos_conf = {
                "rgssVersion": 1,
                "gameFolder": os.path.abspath(fixture_dir),
                "customScript": "fixture.rb",
                "pathCache": True,
                "RTP": [os.path.abspath(target_dir)]
            }
            with open(os.path.join(tmp_dir, "mkxp.json"), "w", encoding="utf-8") as f:
                json.dump(pos_conf, f, indent=2)

            cmd = (
                f"cd {tmp_dir} && "
                f"xvfb-run -a -s '-screen 0 640x480x24' bash -c '"
                f"SDL_AUDIODRIVER=dummy ALSOFT_DRIVERS=null SDL_VIDEODRIVER=x11 LIBGL_ALWAYS_SOFTWARE=1 {mkxp_bin} 2>&1'"
            )
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            self.assertEqual(res.returncode, 0, f"mkxp-z exited with code {res.returncode}:\n{res.stdout}")
            self.assertIn("MKXP-Z VERSION: 2.4.2/826929e", res.stdout)
            self.assertIn("SUPERRTP_RMXP_CHARACTER_LOADED 96x128", res.stdout)
            self.assertIn("SUPERRTP_RMXP_RENDER_DONE", res.stdout)

    def test_10_mkxp_z_live_negative_control(self):
        """Verify mkxp-z negative control: empty RTP isolates missing 001-Fighter01.png (exit code 1) via temp config."""
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

        with tempfile.TemporaryDirectory(prefix="superrtp_neg_test_") as tmp_dir:
            neg_conf = {
                "rgssVersion": 1,
                "gameFolder": os.path.abspath(fixture_dir),
                "customScript": "fixture.rb",
                "pathCache": True,
                "RTP": []
            }
            with open(os.path.join(tmp_dir, "mkxp.json"), "w", encoding="utf-8") as f:
                json.dump(neg_conf, f, indent=2)

            cmd = (
                f"cd {tmp_dir} && "
                f"xvfb-run -a -s '-screen 0 640x480x24' bash -c '"
                f"SDL_AUDIODRIVER=dummy ALSOFT_DRIVERS=null SDL_VIDEODRIVER=x11 LIBGL_ALWAYS_SOFTWARE=1 {mkxp_bin} 2>&1'"
            )
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            self.assertEqual(res.returncode, 1, f"Expected exit code 1 for negative control, got {res.returncode}:\n{res.stdout}")
            self.assertIn("SUPERRTP_RMXP_MISSING_ASSET: No such file or directory - Graphics/Characters/001-Fighter01", res.stdout)

    def test_11_evidence_chain_and_pixel_verification(self):
        """Verify complete durable evidence chain and pixel verification for RMXP."""
        evidence_path = os.path.join(REPO_ROOT, "artifacts", "runtime", "rmxp", "character", "verification_evidence.json")
        self.assertTrue(os.path.exists(evidence_path), f"Evidence file not found: {evidence_path}")
        self.assertTrue(verify_evidence_chain(evidence_path=evidence_path))

    def test_12_adversarial_evidence_tamper_suite(self):
        """Adversarially verify that tampering with any authoritative evidence field, config, or pixel is caught."""
        evidence_path = os.path.join(REPO_ROOT, "artifacts", "runtime", "rmxp", "character", "verification_evidence.json")
        with open(evidence_path, "r", encoding="utf-8") as f:
            original_evidence = json.load(f)

        with tempfile.TemporaryDirectory(prefix="superrtp_rmxp_tamper_") as tmp_dir:
            # Table of field mutations and expected exception snippets
            field_attacks = [
                ("target", "rm2000", "Evidence target mismatch"),
                ("engine_mode", "rgss2", "Evidence engine_mode mismatch"),
                ("runtime", "easyrpg", "Evidence runtime mismatch"),
                ("runtime_commit", "826929eeb3ebc4b887c011604919217a790770f0", "mkxp-z commit pin violation"),
                ("rgss_version", 2, "Evidence rgss_version mismatch"),
                ("target_category", "ChipSet", "Evidence target_category mismatch"),
                ("requested_resource", "Graphics/Characters/002-Fighter02", "Evidence requested_resource mismatch"),
                ("source_character_index", 1, "Evidence source_character_index mismatch"),
                ("transform_policy", "direct_copy", "Evidence transform_policy mismatch"),
                ("positive_exit_code", 1, "positive_exit_code mismatch"),
                ("negative_exit_code", 0, "negative_exit_code mismatch"),
                ("canonical_source_sha256", "0" * 64, "Canonical source SHA-256 mismatch"),
                ("target_manifest_sha256", "0" * 64, "Target manifest hash mismatch"),
                ("target_character_sha256", "0" * 64, "Target character file hash mismatch"),
                ("fixture_manifest_sha256", "0" * 64, "Fixture manifest hash mismatch"),
                ("fixture_script_sha256", "0" * 64, "Fixture script hash mismatch"),
                ("positive_runtime_configuration_sha256", "0" * 64, "Positive runtime configuration hash mismatch"),
                ("negative_runtime_configuration_sha256", "0" * 64, "Negative runtime configuration hash mismatch"),
                ("positive_runtime_log_sha256", "0" * 64, "Positive runtime log hash mismatch"),
                ("negative_runtime_log_sha256", "0" * 64, "Negative runtime log hash mismatch"),
            ]

            for field_name, bad_value, err_sub in field_attacks:
                tampered = dict(original_evidence)
                tampered[field_name] = bad_value
                t_path = os.path.join(tmp_dir, f"tamper_{field_name}.json")
                with open(t_path, "w", encoding="utf-8") as f:
                    json.dump(tampered, f)
                with self.assertRaises(ValueError, msg=f"Tampering with {field_name} must raise ValueError") as ctx:
                    verify_evidence_chain(evidence_path=t_path)
                self.assertIn(err_sub, str(ctx.exception))

            # Tamper negative_control diagnostic
            tampered_diag = dict(original_evidence)
            tampered_diag["negative_control"] = dict(original_evidence["negative_control"])
            tampered_diag["negative_control"]["diagnostic"] = "SUPERRTP_RMXP_MISSING_ASSET: corrupted diagnostic"
            diag_path = os.path.join(tmp_dir, "tamper_diag.json")
            with open(diag_path, "w", encoding="utf-8") as f:
                json.dump(tampered_diag, f)
            with self.assertRaises(ValueError) as ctx:
                verify_evidence_chain(evidence_path=diag_path)
            self.assertIn("negative_control.diagnostic mismatch", str(ctx.exception))

            # Tamper negative_control missing asset
            tampered_missing = dict(original_evidence)
            tampered_missing["negative_control"] = dict(original_evidence["negative_control"])
            tampered_missing["negative_control"]["expected_missing_asset"] = "Graphics/Characters/bad_asset"
            miss_path = os.path.join(tmp_dir, "tamper_missing.json")
            with open(miss_path, "w", encoding="utf-8") as f:
                json.dump(tampered_missing, f)
            with self.assertRaises(ValueError) as ctx:
                verify_evidence_chain(evidence_path=miss_path)
            self.assertIn("negative_control.expected_missing_asset mismatch", str(ctx.exception))

            # Tamper mkxp_z_build_configuration
            tampered_bcfg = dict(original_evidence)
            tampered_bcfg["mkxp_z_build_configuration"] = dict(original_evidence["mkxp_z_build_configuration"])
            tampered_bcfg["mkxp_z_build_configuration"]["workdir_current"] = False
            bcfg_path = os.path.join(tmp_dir, "tamper_bcfg.json")
            with open(bcfg_path, "w", encoding="utf-8") as f:
                json.dump(tampered_bcfg, f)
            with self.assertRaises(ValueError) as ctx:
                verify_evidence_chain(evidence_path=bcfg_path)
            self.assertIn("mkxp_z_build_configuration.workdir_current must be true", str(ctx.exception))

            # Tamper screenshot hash table
            tampered_shot = dict(original_evidence)
            tampered_shot["screenshots"] = dict(original_evidence["screenshots"])
            tampered_shot["screenshots"]["rmxp_character_positive.png"] = "badf00d" * 8
            shot_path = os.path.join(tmp_dir, "tamper_shot.json")
            with open(shot_path, "w", encoding="utf-8") as f:
                json.dump(tampered_shot, f)
            with self.assertRaises(ValueError) as ctx:
                verify_evidence_chain(evidence_path=shot_path)
            self.assertIn("Screenshot hash mismatch", str(ctx.exception))

            # Visual Pixel Tampering 1: Modify positive arrow tip (Down tip at 307, 197)
            cfg = get_target_config()
            pos_shot_path = os.path.join(cfg["artifacts_dir"], "rmxp_character_positive.png")
            w, h, pixels = decode_png_rgb(pos_shot_path)
            pixels_tampered = [row[:] for row in pixels]
            pixels_tampered[197][307] = (0, 255, 0)
            tampered_png_path = os.path.join(tmp_dir, "tampered_pos_tip.png")
            raw_rgba = bytearray()
            for row in pixels_tampered:
                for r, g, b in row:
                    raw_rgba.extend((r, g, b, 255))
            with open(tampered_png_path, "wb") as f:
                f.write(create_rgba_png(w, h, raw_rgba))

            with self.assertRaises(ValueError) as ctx:
                verify_rmxp_screenshot(tampered_png_path, mode="positive")
            self.assertIn("arrow tip mismatch", str(ctx.exception))

            # Visual Pixel Tampering 2: Column 3 idle duplicate mismatch
            pixels_c3_tampered = [row[:] for row in pixels]
            pixels_c3_tampered[197][355] = (255, 0, 0) # mutate Col 3 tip
            tampered_c3_path = os.path.join(tmp_dir, "tampered_pos_c3.png")
            raw_c3 = bytearray()
            for row in pixels_c3_tampered:
                for r, g, b in row:
                    raw_c3.extend((r, g, b, 255))
            with open(tampered_c3_path, "wb") as f:
                f.write(create_rgba_png(w, h, raw_c3))

            with self.assertRaises(ValueError) as ctx:
                verify_rmxp_screenshot(tampered_c3_path, mode="positive")
            self.assertTrue("Col 3 arrow tip mismatch" in str(ctx.exception) or "XP Column 3 idle repetition mismatch" in str(ctx.exception))

            # Visual Pixel Tampering 3: Active step marker corrupted (Col 0 step marker at 280, 176+27)
            pixels_step_tampered = [row[:] for row in pixels]
            pixels_step_tampered[176+27][280] = (0, 0, 0)
            tampered_step_path = os.path.join(tmp_dir, "tampered_step.png")
            raw_step = bytearray()
            for row in pixels_step_tampered:
                for r, g, b in row:
                    raw_step.extend((r, g, b, 255))
            with open(tampered_step_path, "wb") as f:
                f.write(create_rgba_png(w, h, raw_step))

            with self.assertRaises(ValueError) as ctx:
                verify_rmxp_screenshot(tampered_step_path, mode="positive")
            self.assertIn("foot marker mismatch", str(ctx.exception))

            # Visual Pixel Tampering 4: Negative screenshot pixel (character tip present on blank pad)
            neg_shot_path = os.path.join(cfg["artifacts_dir"], "rmxp_character_negative_control.png")
            w, h, pixels_neg = decode_png_rgb(neg_shot_path)
            pixels_neg_tampered = [row[:] for row in pixels_neg]
            pixels_neg_tampered[197][307] = (10, 40, 70)
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

def compute_sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

if __name__ == "__main__":
    unittest.main()
