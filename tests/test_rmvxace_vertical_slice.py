#!/usr/bin/env python3
"""
Comprehensive Automated Test Suite for SuperRTP Phase 1 Task 6:
RPG Maker VX Ace / RGSS3 Standard 8-Character Character Compatibility Slice.
"""

import os
import sys
import json
import zlib
import struct
import shutil
import hashlib
import unittest
import tempfile
import subprocess

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

from build_target import (
    extract_walking_frames,
    pack_vx_family_standard_character_sheet,
    pack_rmvx_character_sheet,
    pack_rmvxace_character_sheet,
    transform_canonical_to_rmvxace_character,
    build_target
)
from validate_target import validate_target, validate_png_vx_family_character, validate_png_rmvxace_character
from png_utils import decode_png_rgb, decode_png_rgba, create_rgba_png
from verify_rmvx_runtime import verify_vx_family_screenshot, PINNED_MKXP_COMMIT, SLOT_THEMES
from verify_rmvxace_runtime import verify_evidence_chain, get_target_config

def compute_sha256(filepath):
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def crop_physical_source_frame(raw_rgba, char_idx, direction, phase):
    """
    Independent ground-truth oracle that directly crops a 24x32 frame from
    the 288x256 canonical raw RGBA buffer using known RM2k physical geometry.
    Physical layout:
      char_x = (char_idx % 4) * 72
      char_y = (char_idx // 4) * 128
      Physical rows:  0: UP, 1: RIGHT, 2: DOWN, 3: LEFT
      Physical cols:  0: STEP_LEFT, 1: IDLE, 2: STEP_RIGHT
    """
    row_map = {"UP": 0, "RIGHT": 1, "DOWN": 2, "LEFT": 3}
    col_map = {"STEP_LEFT": 0, "IDLE": 1, "STEP_RIGHT": 2}

    char_x = (char_idx % 4) * 72
    char_y = (char_idx // 4) * 128

    frame_x = char_x + col_map[phase] * 24
    frame_y = char_y + row_map[direction] * 32

    # Crop 24x32 RGBA pixels directly from 288x256 raw buffer
    frame_bytes = bytearray()
    for py in range(32):
        y = frame_y + py
        start_idx = (y * 288 + frame_x) * 4
        end_idx = start_idx + 24 * 4
        frame_bytes.extend(raw_rgba[start_idx:end_idx])

    return bytes(frame_bytes)

class TestRMVXAceVerticalSlice(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.canonical_rgba_path = os.path.join(
            REPO_ROOT, "registry", "assets", "test_calibration_walking_character.rgba"
        )
        with open(cls.canonical_rgba_path, "rb") as f:
            cls.canonical_rgba = f.read()

        cls.expected_canonical_sha256 = "78ad9a170ac0ba06eb4756f9c9c19923e754e82c22025dab7dfbc46de5c1b790"
        cls.expected_rmvx_char_sha256 = "c6ed8cba9025b982c6300ed5e57a82aee99cc29f7929d81cf1b517ded47550bf"
        cls.expected_rmvxace_char_sha256 = "c6ed8cba9025b982c6300ed5e57a82aee99cc29f7929d81cf1b517ded47550bf"

    def test_01_canonical_asset_integrity(self):
        """Asserts that the clean-room canonical walking-character asset hash is strictly preserved."""
        actual_sha = hashlib.sha256(self.canonical_rgba).hexdigest()
        self.assertEqual(actual_sha, self.expected_canonical_sha256)
        self.assertEqual(len(self.canonical_rgba), 288 * 256 * 4)

    def test_02_semantic_walking_frame_extraction_all_eight(self):
        """
        Asserts semantic frame extraction for all 8 characters against
        the independent physical crop oracle, checking all 96 frames byte-for-byte.
        """
        directions = ("UP", "RIGHT", "DOWN", "LEFT")
        phases = ("STEP_LEFT", "IDLE", "STEP_RIGHT")

        for char_idx in range(8):
            char_frames = extract_walking_frames(self.canonical_rgba, char_idx=char_idx)
            for d in directions:
                for p in phases:
                    extracted = char_frames[d][p]
                    oracle = crop_physical_source_frame(self.canonical_rgba, char_idx, d, p)
                    self.assertEqual(
                        extracted,
                        oracle,
                        f"Mismatch for char {char_idx}, direction {d}, phase {p} vs physical oracle"
                    )

    def test_03_rmvxace_character_packing(self):
        """Verifies VX-family standard 8-character sheet packing and thin wrappers."""
        semantic_characters = [
            extract_walking_frames(self.canonical_rgba, char_idx=i)
            for i in range(8)
        ]
        png_family = pack_vx_family_standard_character_sheet(semantic_characters)
        png_vx = pack_rmvx_character_sheet(semantic_characters)
        png_ace = pack_rmvxace_character_sheet(semantic_characters)

        self.assertEqual(png_family, png_vx)
        self.assertEqual(png_family, png_ace)

        sha = hashlib.sha256(png_ace).hexdigest()
        self.assertEqual(sha, self.expected_rmvxace_char_sha256)

    def test_04_96_cell_exact_semantic_equality(self):
        """Direct byte-for-byte check of all 96 target cells in rmvxace Actor1.png against independent oracle."""
        ace_char_path = os.path.join(REPO_ROOT, "generated", "rmvxace", "Graphics", "Characters", "Actor1.png")
        self.assertTrue(os.path.exists(ace_char_path))

        cw, ch, char_pixels = decode_png_rgba(ace_char_path)
        self.assertEqual(cw, 288)
        self.assertEqual(ch, 256)

        vx_row_order = ["DOWN", "LEFT", "RIGHT", "UP"]
        vx_col_phases = ["STEP_LEFT", "IDLE", "STEP_RIGHT"]

        for char_idx in range(8):
            char_grid_x = char_idx % 4
            char_grid_y = char_idx // 4
            char_base_x = char_grid_x * 72
            char_base_y = char_grid_y * 128

            for row_idx, direction in enumerate(vx_row_order):
                for col_idx, phase in enumerate(vx_col_phases):
                    oracle_frame = crop_physical_source_frame(self.canonical_rgba, char_idx, direction, phase)

                    dst_frame_x = char_base_x + col_idx * 24
                    dst_frame_y = char_base_y + row_idx * 32

                    target_frame = bytearray()
                    for py in range(32):
                        for px in range(24):
                            r, g, b, a = char_pixels[dst_frame_y + py][dst_frame_x + px]
                            target_frame.extend([r, g, b, a])

                    self.assertEqual(
                        bytes(target_frame),
                        oracle_frame,
                        f"Target cell mismatch at char {char_idx}, row {direction} (row {row_idx}), col {phase} (col {col_idx})"
                    )

    def test_05_single_frame_mutation_locality(self):
        """Proves that mutating 1 semantic frame only alters that 1 target cell, leaving all other 95 cells identical."""
        semantic_characters = [
            extract_walking_frames(self.canonical_rgba, char_idx=i)
            for i in range(8)
        ]

        target_char = 3
        target_dir = "RIGHT"
        target_phase = "IDLE"

        orig_frame = bytearray(semantic_characters[target_char][target_dir][target_phase])
        mutated_frame = bytearray(orig_frame)
        mutated_frame[0] = (mutated_frame[0] + 1) % 256
        semantic_characters[target_char][target_dir][target_phase] = bytes(mutated_frame)

        mutated_png = pack_rmvxace_character_sheet(semantic_characters)
        with tempfile.NamedTemporaryFile(suffix=".png") as m_tmp:
            m_tmp.write(mutated_png)
            m_tmp.flush()
            mw, mh, mut_pixels = decode_png_rgba(m_tmp.name)

        orig_char_path = os.path.join(REPO_ROOT, "generated", "rmvxace", "Graphics", "Characters", "Actor1.png")
        _, _, orig_pixels = decode_png_rgba(orig_char_path)

        vx_row_order = ["DOWN", "LEFT", "RIGHT", "UP"]
        vx_col_phases = ["STEP_LEFT", "IDLE", "STEP_RIGHT"]

        mutated_cells_count = 0
        identical_cells_count = 0

        for char_idx in range(8):
            char_grid_x = char_idx % 4
            char_grid_y = char_idx // 4
            char_base_x = char_grid_x * 72
            char_base_y = char_grid_y * 128

            for row_idx, direction in enumerate(vx_row_order):
                for col_idx, phase in enumerate(vx_col_phases):
                    dst_frame_x = char_base_x + col_idx * 24
                    dst_frame_y = char_base_y + row_idx * 32

                    orig_cell = [orig_pixels[dst_frame_y + py][dst_frame_x + px] for py in range(32) for px in range(24)]
                    mut_cell = [mut_pixels[dst_frame_y + py][dst_frame_x + px] for py in range(32) for px in range(24)]

                    is_target = (char_idx == target_char and direction == target_dir and phase == target_phase)
                    if is_target:
                        self.assertNotEqual(orig_cell, mut_cell, "Expected target cell to differ after mutation")
                        mutated_cells_count += 1
                    else:
                        self.assertEqual(orig_cell, mut_cell, f"Unrelated cell ({char_idx},{direction},{phase}) was altered")
                        identical_cells_count += 1

        self.assertEqual(mutated_cells_count, 1)
        self.assertEqual(identical_cells_count, 95)

    def test_06_cross_target_byte_equality_and_manifest_distinction(self):
        """Proves that RMVX and RMVXAce Character payloads are byte-identical while manifests/identities differ."""
        vx_char_path = os.path.join(REPO_ROOT, "generated", "rmvx", "Graphics", "Characters", "Actor1.png")
        ace_char_path = os.path.join(REPO_ROOT, "generated", "rmvxace", "Graphics", "Characters", "Actor1.png")

        with open(vx_char_path, "rb") as f:
            vx_bytes = f.read()
        with open(ace_char_path, "rb") as f:
            ace_bytes = f.read()

        # 1. Byte equality of creative Character payload
        self.assertEqual(vx_bytes, ace_bytes)
        self.assertEqual(hashlib.sha256(vx_bytes).hexdigest(), self.expected_rmvx_char_sha256)
        self.assertEqual(hashlib.sha256(ace_bytes).hexdigest(), self.expected_rmvxace_char_sha256)

        # 2. Manifest and engine identity separation
        vx_manifest_path = os.path.join(REPO_ROOT, "generated", "rmvx", "manifest.json")
        ace_manifest_path = os.path.join(REPO_ROOT, "generated", "rmvxace", "manifest.json")

        with open(vx_manifest_path, "r", encoding="utf-8") as f:
            vx_manifest = json.load(f)
        with open(ace_manifest_path, "r", encoding="utf-8") as f:
            ace_manifest = json.load(f)

        self.assertEqual(vx_manifest["target"], "rmvx")
        self.assertEqual(vx_manifest["engine"], "RPG Maker VX")
        self.assertEqual(vx_manifest["entries"][0]["transform_policy"], "rm2k8_to_rgss2_standard_character_sheet_v1")

        self.assertEqual(ace_manifest["target"], "rmvxace")
        self.assertEqual(ace_manifest["engine"], "RPG Maker VX Ace")
        self.assertEqual(ace_manifest["entries"][0]["transform_policy"], "rm2k8_to_rgss3_standard_character_sheet_v1")

        self.assertNotEqual(vx_manifest["target"], ace_manifest["target"])
        self.assertNotEqual(vx_manifest["entries"][0]["transform_policy"], ace_manifest["entries"][0]["transform_policy"])

    def test_07_independent_build_no_rmvx_dependency(self):
        """Verifies RMVXAce can build into a clean output directory without consulting generated/rmvx."""
        with tempfile.TemporaryDirectory() as td:
            build_target("rmvxace", output_dir=td, clean=True)
            emitted_char = os.path.join(td, "Graphics", "Characters", "Actor1.png")
            self.assertTrue(os.path.exists(emitted_char))
            with open(emitted_char, "rb") as f:
                data = f.read()
            self.assertEqual(hashlib.sha256(data).hexdigest(), self.expected_rmvxace_char_sha256)

    def test_08_rmvxace_build_reproducibility(self):
        """A/B build reproducibility: two separate builds of RMVXAce must be bit-for-bit identical."""
        with tempfile.TemporaryDirectory() as td_a, tempfile.TemporaryDirectory() as td_b:
            build_target("rmvxace", output_dir=td_a, clean=True, timestamp="1970-01-01T00:00:00Z")
            build_target("rmvxace", output_dir=td_b, clean=True, timestamp="1970-01-01T00:00:00Z")

            char_a = os.path.join(td_a, "Graphics", "Characters", "Actor1.png")
            char_b = os.path.join(td_b, "Graphics", "Characters", "Actor1.png")
            with open(char_a, "rb") as f_a, open(char_b, "rb") as f_b:
                self.assertEqual(f_a.read(), f_b.read())

            man_a = os.path.join(td_a, "manifest.json")
            man_b = os.path.join(td_b, "manifest.json")
            with open(man_a, "rb") as f_a, open(man_b, "rb") as f_b:
                self.assertEqual(f_a.read(), f_b.read())

    def test_09_frozen_baseline_regression_integrity(self):
        """Verifies that all accepted Tasks 1-5 golden outputs remain strictly frozen and unaltered."""
        frozen_checks = [
            ("registry/assets/test_calibration_walking_character.rgba", "78ad9a170ac0ba06eb4756f9c9c19923e754e82c22025dab7dfbc46de5c1b790"),
            ("registry/assets/test_calibration_map_chipset.rgba", "4a4f5bdf6dbbbd12b23e358d1780eb8c3163ac81b25f4b2e3b366f50ab54454f"),
            ("generated/rm2000/CharSet/Actor1.png", "7fde5157142d929404f3fc3b599cbd6c558ef74b2135ac1172db53dd88641ee6"),
            ("generated/rm2003/CharSet/Actor1.png", "7fde5157142d929404f3fc3b599cbd6c558ef74b2135ac1172db53dd88641ee6"),
            ("generated/rm2000/ChipSet/World.png", "8a1c5552c544fb5195a92ab8f2f0e84b11d95fa3929250aa74b69630067fe137"),
            ("generated/rm2003/ChipSet/World.png", "8a1c5552c544fb5195a92ab8f2f0e84b11d95fa3929250aa74b69630067fe137"),
            ("generated/rmxp/Graphics/Characters/001-Fighter01.png", "b4e81694247632b5580b5eef55a17e61c6afd709092de0e574aed70b41759743"),
            ("generated/rmvx/Graphics/Characters/Actor1.png", "c6ed8cba9025b982c6300ed5e57a82aee99cc29f7929d81cf1b517ded47550bf"),
        ]
        for rel_path, expected_sha in frozen_checks:
            full_path = os.path.join(REPO_ROOT, rel_path)
            self.assertTrue(os.path.exists(full_path), f"Frozen file missing: {rel_path}")
            self.assertEqual(compute_sha256(full_path), expected_sha, f"Frozen hash mismatch for {rel_path}")

    def test_10_target_validator_positive_and_adversarial_rejections(self):
        """Verifies target pack validation passes on committed rmvxace, and fails on 8+ adversarial mutations."""
        res = validate_target("rmvxace")
        self.assertEqual(res, 0)

        real_target_dir = os.path.join(REPO_ROOT, "generated", "rmvxace")
        manifest_path = os.path.join(real_target_dir, "manifest.json")
        with open(manifest_path, "r", encoding="utf-8") as f:
            valid_manifest = json.load(f)

        attack_vectors = [
            ("wrong category", {"category": "ChipSet"}),
            ("wrong target SHA", {"sha256": "0" * 64}),
            ("inverted source indices", {"source_character_indices": [7, 6, 5, 4, 3, 2, 1, 0]}),
            ("missing transform policy", {"_delete_": "transform_policy"}),
            ("wrong transform policy", {"transform_policy": "rm2k_to_rgss1_character_4x4"}),
        ]

        for attack_name, mutation in attack_vectors:
            with tempfile.TemporaryDirectory() as td:
                shutil.copytree(real_target_dir, td, dirs_exist_ok=True)
                mutated_manifest = json.loads(json.dumps(valid_manifest))
                entry = mutated_manifest["entries"][0]
                if "_delete_" in mutation:
                    entry.pop(mutation["_delete_"], None)
                else:
                    entry.update(mutation)

                with open(os.path.join(td, "manifest.json"), "w", encoding="utf-8") as f:
                    json.dump(mutated_manifest, f, indent=2)

                self.assertEqual(
                    validate_target("rmvxace", target_dir=td),
                    1,
                    f"Validator unexpectedly passed under attack: {attack_name}"
                )

        # Top-level manifest identity attacks
        top_level_attacks = [
            ("wrong top-level target", {"target": "rmvx"}),
            ("wrong top-level engine", {"engine": "RPG Maker VX"}),
            ("wrong top-level target_name", {"target_name": "RPG Maker VX Runtime Package"}),
        ]

        for attack_name, mutation in top_level_attacks:
            with tempfile.TemporaryDirectory() as td:
                shutil.copytree(real_target_dir, td, dirs_exist_ok=True)
                mutated_manifest = json.loads(json.dumps(valid_manifest))
                mutated_manifest.update(mutation)
                with open(os.path.join(td, "manifest.json"), "w", encoding="utf-8") as f:
                    json.dump(mutated_manifest, f, indent=2)

                self.assertEqual(
                    validate_target("rmvxace", target_dir=td),
                    1,
                    f"Validator unexpectedly passed under top-level attack: {attack_name}"
                )

        # PNG image mutation attack: permute directional rows (Row 0 DOWN swapped with Row 3 UP)
        with tempfile.TemporaryDirectory() as td:
            shutil.copytree(real_target_dir, td, dirs_exist_ok=True)
            png_path = os.path.join(td, "Graphics", "Characters", "Actor1.png")
            _, _, px = decode_png_rgba(png_path)
            permuted_px = [row[:] for row in px]

            # In Character block 0 (top-left 72x128), swap Row 0 (y: 0..31) and Row 3 (y: 96..127)
            for y in range(32):
                permuted_px[y][:72] = px[96 + y][:72]
                permuted_px[96 + y][:72] = px[y][:72]

            flat_rgba = bytearray()
            for row in permuted_px:
                for r, g, b, a in row:
                    flat_rgba.extend([r, g, b, a])

            bad_png = create_rgba_png(288, 256, bytes(flat_rgba))
            with open(png_path, "wb") as f:
                f.write(bad_png)

            # Update manifest sha to match permuted png so it fails specifically on PNG geometry
            mutated_manifest = json.loads(json.dumps(valid_manifest))
            mutated_manifest["entries"][0]["sha256"] = hashlib.sha256(bad_png).hexdigest()
            with open(os.path.join(td, "manifest.json"), "w", encoding="utf-8") as f:
                json.dump(mutated_manifest, f, indent=2)

            self.assertEqual(
                validate_target("rmvxace", target_dir=td),
                1,
                "Validator unexpectedly passed on directional-row permuted PNG"
            )

    def test_11_clean_room_fixture_integrity(self):
        """Verifies clean-room RGSS3 fixture integrity and hash-bound manifest."""
        fixture_dir = os.path.join(REPO_ROOT, "tests", "fixtures", "rmvxace_character_min")
        self.assertTrue(os.path.exists(fixture_dir))

        manifest_path = os.path.join(fixture_dir, "fixture_manifest.json")
        self.assertTrue(os.path.exists(manifest_path))

        with open(manifest_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        self.assertEqual(meta["engine"], "RPG Maker VX Ace")
        self.assertEqual(meta["rgss_version"], 3)
        self.assertIn("clean_room_attestation", meta)

        for filename, fileinfo in meta["files"].items():
            filepath = os.path.join(fixture_dir, filename)
            self.assertTrue(os.path.exists(filepath), f"Missing fixture file: {filename}")
            self.assertEqual(compute_sha256(filepath), fileinfo["sha256"])

    def test_12_rmvxace_positive_runtime_evidence_and_markers(self):
        """Verifies mkxp-z RGSS3 positive runtime evidence and deterministic log markers."""
        mkxp_bin = shutil.which("mkxp-z") or os.path.expanduser("~/.local/bin/mkxp-z")
        if not (os.path.exists(mkxp_bin) and os.access(mkxp_bin, os.X_OK)):
            if os.environ.get("SUPERRTP_REQUIRE_RUNTIME") == "1":
                self.fail(f"mkxp-z required by SUPERRTP_REQUIRE_RUNTIME but not found at {mkxp_bin}")
            self.skipTest("mkxp-z runner not available")

        # Check positive log output
        log_path = os.path.join(REPO_ROOT, "artifacts", "runtime", "rmvxace", "character", "positive_runtime.log")
        self.assertTrue(os.path.exists(log_path))
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            log_content = f.read()

        self.assertIn("RGSS version 3 (RPG Maker VX Ace)", log_content)
        self.assertIn("SUPERRTP_RGSS3_SCREEN 544x416", log_content)
        self.assertIn("SUPERRTP_RMVXACE_CHARACTER_LOADED 288x256", log_content)
        self.assertIn("SUPERRTP_RMVXACE_RENDER_DONE", log_content)

    def test_13_rmvxace_negative_runtime_execution(self):
        """Verifies live mkxp-z RGSS3 negative runtime execution (missing Actor1 isolation)."""
        mkxp_bin = shutil.which("mkxp-z") or os.path.expanduser("~/.local/bin/mkxp-z")
        if not (os.path.exists(mkxp_bin) and os.access(mkxp_bin, os.X_OK)):
            if os.environ.get("SUPERRTP_REQUIRE_RUNTIME") == "1":
                self.fail(f"mkxp-z required by SUPERRTP_REQUIRE_RUNTIME but not found at {mkxp_bin}")
            self.skipTest("mkxp-z runner not available")

        log_path = os.path.join(REPO_ROOT, "artifacts", "runtime", "rmvxace", "character", "negative_runtime.log")
        self.assertTrue(os.path.exists(log_path))
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            log_content = f.read()

        self.assertIn("SUPERRTP_RMVXACE_MISSING_ASSET:", log_content)
        self.assertIn("Graphics/Characters/Actor1", log_content)

    def test_14_evidence_chain_integrity(self):
        """Verifies the complete durable evidence chain for rmvxace Character compatibility."""
        res = verify_evidence_chain()
        self.assertEqual(res, 0)

    def test_15_adversarial_evidence_tamper_suite(self):
        """Systematically mutates 22+ top-level fields, 9 build config fields, and screenshot pixels."""
        cfg = get_target_config()
        with open(cfg["evidence_path"], "r", encoding="utf-8") as f:
            valid_evidence = json.load(f)

        tamper_cases = [
            ("target", "rmvx"),
            ("engine", "RPG Maker VX"),
            ("engine_mode", "rgss2"),
            ("rgss_version", 2),
            ("runtime", "easyrpg"),
            ("runtime_commit", "deadbeef" * 5),
            ("startup_log_identity", "RGSS version 2 (RPG Maker VX) "),
            ("category", "ChipSet"),
            ("requested_resource", "Graphics/Characters/Actor2"),
            ("canonical_asset_id", "test.calibration.hero"),
            ("canonical_asset_sha256", "0" * 64),
            ("source_character_indices", [0, 1, 2, 3]),
            ("transform_policy", "rm2k8_to_rgss2_standard_character_sheet_v1"),
            ("target_manifest_sha256", "0" * 64),
            ("actor1_png_sha256", "0" * 64),
            ("rmvx_actor1_reference_sha256", "0" * 64),
            ("rmvx_byte_equality", "DIFFERENT"),
            ("fixture_script_sha256", "0" * 64),
            ("fixture_manifest_sha256", "0" * 64),
            ("positive_exit_code", 1),
            ("negative_exit_code", 0),
            ("positive_runtime_log_sha256", "0" * 64),
            ("negative_runtime_log_sha256", "0" * 64),
            ("negative_diagnostic", "SUPERRTP_RMVXACE_MISSING_ASSET: File not found - Graphics/Characters/Actor2"),
            ("positive_screenshot_sha256", "0" * 64),
            ("negative_screenshot_sha256", "0" * 64),
        ]

        for field, bad_value in tamper_cases:
            tampered = json.loads(json.dumps(valid_evidence))
            tampered[field] = bad_value

            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
                json.dump(tampered, tf, indent=2)
                tf_path = tf.name

            try:
                with self.assertRaises(Exception, msg=f"Tamper on '{field}' unexpectedly passed"):
                    verify_evidence_chain(custom_evidence_path=tf_path)
            finally:
                if os.path.exists(tf_path):
                    os.unlink(tf_path)

        # Coordinated portable config attacks (where sha256 is recomputed to match tampered object)
        coord_config_attacks = [
            ("positive RTP points to foreign directory", "positive_portable_config", "RTP", ["generated/rmvx"]),
            ("positive RTP points to empty list", "positive_portable_config", "RTP", []),
            ("negative RTP points to generated/rmvxace", "negative_portable_config", "RTP", ["generated/rmvxace"]),
            ("positive customScript altered", "positive_portable_config", "customScript", "other.rb"),
            ("negative customScript altered", "negative_portable_config", "customScript", "other.rb"),
            ("positive pathCache disabled", "positive_portable_config", "pathCache", False),
            ("negative pathCache disabled", "negative_portable_config", "pathCache", False),
            ("positive gameFolder wrong", "positive_portable_config", "gameFolder", "tests/fixtures/wrong"),
            ("negative gameFolder wrong", "negative_portable_config", "gameFolder", "tests/fixtures/wrong"),
            ("positive rgssVersion wrong", "positive_portable_config", "rgssVersion", 2),
            ("negative rgssVersion wrong", "negative_portable_config", "rgssVersion", 2),
        ]

        for desc, cfg_key, prop, bad_val in coord_config_attacks:
            tampered = json.loads(json.dumps(valid_evidence))
            tampered[cfg_key][prop] = bad_val
            tampered[f"{cfg_key}_sha256"] = hashlib.sha256(
                json.dumps(tampered[cfg_key], sort_keys=True).encode("utf-8")
            ).hexdigest()

            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
                json.dump(tampered, tf, indent=2)
                tf_path = tf.name

            try:
                with self.assertRaises(Exception, msg=f"Coordinated config tamper '{desc}' unexpectedly passed"):
                    verify_evidence_chain(custom_evidence_path=tf_path)
            finally:
                if os.path.exists(tf_path):
                    os.unlink(tf_path)

        # Coordinated positive runtime log attacks (log modified and hash recomputed)
        log_attacks = [
            ("omitted RGSS3 startup identity banner", lambda s: s.replace("RGSS version 3 (RPG Maker VX Ace)", "RGSS version 2 (RPG Maker VX)")),
            ("omitted screen resolution marker", lambda s: s.replace("SUPERRTP_RGSS3_SCREEN 544x416\n", "")),
            ("omitted character loaded marker", lambda s: s.replace("SUPERRTP_RMVXACE_CHARACTER_LOADED 288x256\n", "")),
            ("omitted render done marker", lambda s: s.replace("SUPERRTP_RMVXACE_RENDER_DONE\n", "")),
        ]

        for desc, mutator in log_attacks:
            with tempfile.TemporaryDirectory() as td:
                shutil.copytree(cfg["artifacts_dir"], td, dirs_exist_ok=True)
                td_pos_log = os.path.join(td, "positive_runtime.log")
                with open(td_pos_log, "r", encoding="utf-8") as f:
                    orig_log = f.read()

                mutated_log = mutator(orig_log)
                self.assertNotEqual(orig_log, mutated_log, f"Mutator for '{desc}' made no changes")
                with open(td_pos_log, "w", encoding="utf-8") as f:
                    f.write(mutated_log)

                tampered = json.loads(json.dumps(valid_evidence))
                tampered["positive_runtime_log_sha256"] = compute_sha256(td_pos_log)

                td_ev_path = os.path.join(td, "verification_evidence.json")
                with open(td_ev_path, "w", encoding="utf-8") as f:
                    json.dump(tampered, f, indent=2)

                with self.assertRaises(Exception, msg=f"Coordinated log tamper '{desc}' unexpectedly passed"):
                    verify_evidence_chain(custom_evidence_path=td_ev_path)

        # Attack nested build_metadata fields
        build_meta_attacks = [
            ("runtime", "easyrpg"),
            ("pinned_commit", "deadbeef" * 5),
            ("workdir_current", False),
            ("static_executable", True),
            ("shared_fluid", True),
            ("build_config_revision", "buildcfg1"),
            ("mri_version", ""),
        ]

        for b_field, b_val in build_meta_attacks:
            tampered = json.loads(json.dumps(valid_evidence))
            tampered["build_metadata"][b_field] = b_val

            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
                json.dump(tampered, tf, indent=2)
                tf_path = tf.name

            try:
                with self.assertRaises(Exception, msg=f"Tamper on build_metadata['{b_field}'] unexpectedly passed"):
                    verify_evidence_chain(custom_evidence_path=tf_path)
            finally:
                if os.path.exists(tf_path):
                    os.unlink(tf_path)

        # Attack screenshot pixel tampering (corrupt pad TL corner marker)
        pos_shot_path = os.path.join(cfg["artifacts_dir"], "rmvxace_character_positive.png")
        _, _, pixels = decode_png_rgb(pos_shot_path)
        corrupted_pixels = [row[:] for row in pixels]
        corrupted_pixels[70][118] = (0, 0, 0)  # corrupt TL corner from red to black

        flat_rgba = bytearray()
        for row in corrupted_pixels:
            for r, g, b in row:
                flat_rgba.extend([r, g, b, 255])

        bad_png = create_rgba_png(544, 416, bytes(flat_rgba))

        with tempfile.NamedTemporaryFile("wb", suffix=".png", delete=False) as tf_png:
            tf_png.write(bad_png)
            tf_png_path = tf_png.name

        try:
            with self.assertRaises(Exception, msg="Screenshot pixel corruption unexpectedly passed"):
                verify_vx_family_screenshot(tf_png_path, mode="positive")
        finally:
            if os.path.exists(tf_png_path):
                os.unlink(tf_png_path)

if __name__ == "__main__":
    unittest.main()
