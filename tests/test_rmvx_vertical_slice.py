#!/usr/bin/env python3
"""
Comprehensive Automated Test Suite for SuperRTP Phase 1 Task 5:
RPG Maker VX / RGSS2 Standard 8-Character Character Compatibility Slice.
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
    pack_rmvx_character_sheet,
    transform_canonical_to_rmvx_character,
    build_target
)
from validate_target import validate_target, validate_png_rmvx_character
from png_utils import decode_png_rgb, decode_png_rgba, create_rgba_png
from verify_rmvx_runtime import (
    verify_evidence_chain,
    get_target_config,
    verify_rmvx_screenshot,
    PINNED_MKXP_COMMIT,
    SLOT_THEMES
)

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

class TestRMVXVerticalSlice(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.canonical_rgba_path = os.path.join(
            REPO_ROOT, "registry", "assets", "test_calibration_walking_character.rgba"
        )
        with open(cls.canonical_rgba_path, "rb") as f:
            cls.canonical_rgba = f.read()

        cls.expected_canonical_sha256 = "78ad9a170ac0ba06eb4756f9c9c19923e754e82c22025dab7dfbc46de5c1b790"
        cls.expected_rmvx_char_sha256 = "c6ed8cba9025b982c6300ed5e57a82aee99cc29f7929d81cf1b517ded47550bf"

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

        all_chars = []
        for char_idx in range(8):
            frames = extract_walking_frames(self.canonical_rgba, char_idx=char_idx)
            self.assertIsInstance(frames, dict)
            self.assertEqual(set(frames.keys()), set(directions))
            for d in directions:
                self.assertEqual(set(frames[d].keys()), set(phases))
                for p in phases:
                    frame_bytes = frames[d][p]
                    self.assertEqual(len(frame_bytes), 24 * 32 * 4)

                    # Independent ground-truth oracle comparison:
                    oracle_bytes = crop_physical_source_frame(self.canonical_rgba, char_idx, d, p)
                    self.assertEqual(
                        frame_bytes,
                        oracle_bytes,
                        f"Independent physical oracle mismatch at char {char_idx}, direction {d}, phase {p}"
                    )
            all_chars.append(frames)

        # Ensure different characters have distinct pixels (e.g. outline/body colors)
        char0_idle_down = all_chars[0]["DOWN"]["IDLE"]
        char1_idle_down = all_chars[1]["DOWN"]["IDLE"]
        self.assertNotEqual(char0_idle_down, char1_idle_down)

        # Bounds checking
        with self.assertRaises(ValueError):
            extract_walking_frames(self.canonical_rgba, char_idx=-1)
        with self.assertRaises(ValueError):
            extract_walking_frames(self.canonical_rgba, char_idx=8)

    def test_03_rmvx_character_packing(self):
        """Asserts RPG Maker VX standard 8-character sheet packing geometry, chunk structure, and alpha distribution."""
        semantic_chars = [extract_walking_frames(self.canonical_rgba, char_idx=i) for i in range(8)]
        png_bytes = pack_rmvx_character_sheet(semantic_chars)

        # PNG signature
        self.assertTrue(png_bytes.startswith(b"\x89PNG\r\n\x1a\n"))

        # IHDR inspection
        w, h, bit_depth, color_type = struct.unpack(">IIBB", png_bytes[16:26])
        self.assertEqual(w, 288)
        self.assertEqual(h, 256)
        self.assertEqual(bit_depth, 8)
        self.assertEqual(color_type, 6)  # Truecolor RGBA

        # Ensure no PLTE chunk
        self.assertNotIn(b"PLTE", png_bytes)

        # Output SHA-256 match
        actual_sha = hashlib.sha256(png_bytes).hexdigest()
        self.assertEqual(actual_sha, self.expected_rmvx_char_sha256)

    def test_04_96_cell_exact_semantic_equality(self):
        """
        Mechanically compares ALL 96 cells in the generated 288x256 VX sheet
        directly against the independent physical source crop oracle without
        calling extract_walking_frames().
        """
        # Decode generated PNG to raw RGBA bytes
        w, h, pixels_rgba = decode_png_rgba(os.path.join(REPO_ROOT, "generated", "rmvx", "Graphics", "Characters", "Actor1.png"))
        self.assertEqual(w, 288)
        self.assertEqual(h, 256)

        target_row_order = ["DOWN", "LEFT", "RIGHT", "UP"]
        target_col_phases = ["STEP_LEFT", "IDLE", "STEP_RIGHT"]

        tested_cells = 0
        for char_idx in range(8):
            char_grid_x = char_idx % 4
            char_grid_y = char_idx // 4
            char_base_x = char_grid_x * 72
            char_base_y = char_grid_y * 128

            for row_idx, direction in enumerate(target_row_order):
                for col_idx, phase in enumerate(target_col_phases):
                    # Expected frame bytes from independent direct physical crop oracle
                    expected_frame_bytes = crop_physical_source_frame(
                        self.canonical_rgba, char_idx, direction, phase
                    )

                    # Extract target cell (24x32 RGBA) from pixels_rgba
                    cell_bytes = bytearray()
                    cell_x = char_base_x + col_idx * 24
                    cell_y = char_base_y + row_idx * 32

                    for py in range(32):
                        for px in range(24):
                            r, g, b, a = pixels_rgba[cell_y + py][cell_x + px]
                            cell_bytes.extend([r, g, b, a])

                    self.assertEqual(
                        bytes(cell_bytes),
                        expected_frame_bytes,
                        f"Mismatch at char {char_idx}, direction {direction}, phase {phase} (cell at {cell_x},{cell_y})"
                    )
                    tested_cells += 1

        self.assertEqual(tested_cells, 96, "Expected exactly 96 cells to be verified against independent oracle")

    def test_05_single_frame_mutation_locality(self):
        """
        Verifies that mutating exactly one semantic frame only alters the corresponding
        target cell in the packed 288x256 sheet, leaving all other 95 cells 100% byte-identical.
        """
        # Extract baseline semantic frames
        baseline_chars = [extract_walking_frames(self.canonical_rgba, char_idx=i) for i in range(8)]
        baseline_png = pack_rmvx_character_sheet(baseline_chars)
        with tempfile.NamedTemporaryFile(suffix=".png") as b_tmp:
            b_tmp.write(baseline_png)
            b_tmp.flush()
            _, _, b_pixels = decode_png_rgba(b_tmp.name)

        # Mutate exactly one frame: Character 3, RIGHT, IDLE
        mut_char_idx = 3
        mut_direction = "RIGHT"
        mut_phase = "IDLE"

        mut_chars = []
        for i in range(8):
            char_dict = {}
            for d in ("UP", "RIGHT", "DOWN", "LEFT"):
                char_dict[d] = dict(baseline_chars[i][d])
            mut_chars.append(char_dict)

        # Flip the color of the first pixel in that one frame
        orig_frame = bytearray(mut_chars[mut_char_idx][mut_direction][mut_phase])
        orig_frame[0] = (orig_frame[0] + 128) % 256  # mutate red byte
        orig_frame[3] = 255  # ensure opaque
        mut_chars[mut_char_idx][mut_direction][mut_phase] = bytes(orig_frame)

        mut_png = pack_rmvx_character_sheet(mut_chars)
        with tempfile.NamedTemporaryFile(suffix=".png") as m_tmp:
            m_tmp.write(mut_png)
            m_tmp.flush()
            _, _, m_pixels = decode_png_rgba(m_tmp.name)

        target_row_order = ["DOWN", "LEFT", "RIGHT", "UP"]
        target_col_phases = ["STEP_LEFT", "IDLE", "STEP_RIGHT"]

        for char_idx in range(8):
            char_grid_x = char_idx % 4
            char_grid_y = char_idx // 4
            char_base_x = char_grid_x * 72
            char_base_y = char_grid_y * 128

            for row_idx, direction in enumerate(target_row_order):
                for col_idx, phase in enumerate(target_col_phases):
                    cell_x = char_base_x + col_idx * 24
                    cell_y = char_base_y + row_idx * 32

                    b_cell = [b_pixels[cell_y + py][cell_x + px] for py in range(32) for px in range(24)]
                    m_cell = [m_pixels[cell_y + py][cell_x + px] for py in range(32) for px in range(24)]

                    if (char_idx, direction, phase) == (mut_char_idx, mut_direction, mut_phase):
                        self.assertNotEqual(
                            b_cell, m_cell,
                            f"Mutated cell at ({char_idx}, {direction}, {phase}) did not change!"
                        )
                    else:
                        self.assertEqual(
                            b_cell, m_cell,
                            f"Unrelated cell at ({char_idx}, {direction}, {phase}) was corrupted by mutation!"
                        )

    def test_06_character_index_preservation_and_permutation(self):
        """
        Verifies that Character block N derives strictly from source Character N.
        Swapping two semantic characters before packing must swap exactly their corresponding blocks.
        """
        semantic_chars = [extract_walking_frames(self.canonical_rgba, char_idx=i) for i in range(8)]

        # Permute: swap character 1 and character 3
        permuted_chars = list(semantic_chars)
        permuted_chars[1], permuted_chars[3] = permuted_chars[3], permuted_chars[1]

        permuted_png = pack_rmvx_character_sheet(permuted_chars)

        with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
            tmp.write(permuted_png)
            tmp.flush()
            _, _, p_pixels = decode_png_rgba(tmp.name)

        with open(os.path.join(REPO_ROOT, "generated", "rmvx", "Graphics", "Characters", "Actor1.png"), "rb") as f:
            normal_png = f.read()
        with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
            tmp.write(normal_png)
            tmp.flush()
            _, _, n_pixels = decode_png_rgba(tmp.name)

        # Block 1 in permuted must match Block 3 in normal
        # Block 3 in permuted must match Block 1 in normal
        # Block 0 and Block 2 must be completely unchanged
        for py in range(128):
            for px in range(72):
                # Block 0 check (unchanged)
                self.assertEqual(p_pixels[py][px], n_pixels[py][px])
                # Block 1 check (now has normal block 3)
                self.assertEqual(p_pixels[py][72 + px], n_pixels[py][216 + px])
                # Block 3 check (now has normal block 1)
                self.assertEqual(p_pixels[py][216 + px], n_pixels[py][72 + px])

    def test_07_adversarial_packer_validation(self):
        """Asserts that pack_rmvx_character_sheet strictly rejects malformed or invalid inputs."""
        semantic_chars = [extract_walking_frames(self.canonical_rgba, char_idx=i) for i in range(8)]

        # Reject fewer than 8 characters
        with self.assertRaises(ValueError):
            pack_rmvx_character_sheet(semantic_chars[:7])

        # Reject more than 8 characters
        with self.assertRaises(ValueError):
            pack_rmvx_character_sheet(semantic_chars + [semantic_chars[0]])

        # Reject missing direction in one character
        corrupt_chars = [dict(c) for c in semantic_chars]
        corrupt_chars[2] = {k: v for k, v in corrupt_chars[2].items() if k != "DOWN"}
        with self.assertRaises(KeyError):
            pack_rmvx_character_sheet(corrupt_chars)

        # Reject missing phase in one direction
        corrupt_chars2 = [dict(c) for c in semantic_chars]
        corrupt_chars2[4]["LEFT"] = {k: v for k, v in corrupt_chars2[4]["LEFT"].items() if k != "STEP_RIGHT"}
        with self.assertRaises(KeyError):
            pack_rmvx_character_sheet(corrupt_chars2)

        # Reject malformed frame length
        corrupt_chars3 = [dict(c) for c in semantic_chars]
        corrupt_chars3[0]["UP"]["IDLE"] = b"\x00" * 100
        with self.assertRaises(ValueError):
            pack_rmvx_character_sheet(corrupt_chars3)

    def test_08_rmvx_build_reproducibility(self):
        """Asserts bit-for-bit build reproducibility across two clean target builds."""
        with tempfile.TemporaryDirectory() as dir_a, tempfile.TemporaryDirectory() as dir_b:
            build_target("rmvx", output_dir=dir_a, clean=True, timestamp="1970-01-01T00:00:00Z")
            build_target("rmvx", output_dir=dir_b, clean=True, timestamp="1970-01-01T00:00:00Z")

            for root, _, files in os.walk(dir_a):
                for f in files:
                    path_a = os.path.join(root, f)
                    rel = os.path.relpath(path_a, dir_a)
                    path_b = os.path.join(dir_b, rel)
                    self.assertTrue(os.path.exists(path_b), f"Missing {rel} in build B")
                    self.assertEqual(
                        compute_sha256(path_a),
                        compute_sha256(path_b),
                        f"Non-reproducible output for {rel}"
                    )

    def test_09_frozen_baseline_regression_integrity(self):
        """Ensures that Tasks 1-4 baseline golden hashes are strictly preserved."""
        golden_hashes = {
            "rm2000 CharSet/Actor1.png": ("generated/rm2000/CharSet/Actor1.png", "7fde5157142d929404f3fc3b599cbd6c558ef74b2135ac1172db53dd88641ee6"),
            "rm2000 ChipSet/World.png": ("generated/rm2000/ChipSet/World.png", "8a1c5552c544fb5195a92ab8f2f0e84b11d95fa3929250aa74b69630067fe137"),
            "rm2003 CharSet/Hero1.png": ("generated/rm2003/CharSet/Hero1.png", "7fde5157142d929404f3fc3b599cbd6c558ef74b2135ac1172db53dd88641ee6"),
            "rm2003 ChipSet/World.png": ("generated/rm2003/ChipSet/World.png", "8a1c5552c544fb5195a92ab8f2f0e84b11d95fa3929250aa74b69630067fe137"),
            "rmxp Graphics/Characters/001-Fighter01.png": ("generated/rmxp/Graphics/Characters/001-Fighter01.png", "b4e81694247632b5580b5eef55a17e61c6afd709092de0e574aed70b41759743")
        }
        for name, (rel_path, expected_sha) in golden_hashes.items():
            full_path = os.path.join(REPO_ROOT, rel_path)
            self.assertTrue(os.path.exists(full_path), f"Missing baseline asset: {full_path}")
            act_sha = compute_sha256(full_path)
            self.assertEqual(act_sha, expected_sha, f"Baseline regression in {name}!")

    def test_10_rmvx_target_validator_adversarial_rejections(self):
        """
        Adversarial validator test covering wrong source indices, missing/wrong transform policy,
        wrong category, wrong target hash, and deliberate directional-row permutation.
        """
        clean_dir = os.path.join(REPO_ROOT, "generated", "rmvx")
        self.assertEqual(validate_target("rmvx", target_dir=clean_dir), 0, "Base target must validate with code 0")

        # 1. Inverted source_character_indices in manifest
        with tempfile.TemporaryDirectory(prefix="val_tamper_") as tmp_dir:
            shutil.copytree(clean_dir, tmp_dir, dirs_exist_ok=True)
            mp = os.path.join(tmp_dir, "manifest.json")
            with open(mp, "r", encoding="utf-8") as f:
                d = json.load(f)
            d["entries"][0]["source_character_indices"] = [7, 6, 5, 4, 3, 2, 1, 0]
            with open(mp, "w", encoding="utf-8") as f:
                json.dump(d, f)
            self.assertEqual(validate_target("rmvx", target_dir=tmp_dir), 1, "Validator must reject inverted source indices")

        # 2. Missing transform_policy in manifest
        with tempfile.TemporaryDirectory(prefix="val_tamper_") as tmp_dir:
            shutil.copytree(clean_dir, tmp_dir, dirs_exist_ok=True)
            mp = os.path.join(tmp_dir, "manifest.json")
            with open(mp, "r", encoding="utf-8") as f:
                d = json.load(f)
            del d["entries"][0]["transform_policy"]
            with open(mp, "w", encoding="utf-8") as f:
                json.dump(d, f)
            self.assertEqual(validate_target("rmvx", target_dir=tmp_dir), 1, "Validator must reject missing transform policy")

        # 3. Wrong transform_policy in manifest
        with tempfile.TemporaryDirectory(prefix="val_tamper_") as tmp_dir:
            shutil.copytree(clean_dir, tmp_dir, dirs_exist_ok=True)
            mp = os.path.join(tmp_dir, "manifest.json")
            with open(mp, "r", encoding="utf-8") as f:
                d = json.load(f)
            d["entries"][0]["transform_policy"] = "direct_copy"
            with open(mp, "w", encoding="utf-8") as f:
                json.dump(d, f)
            self.assertEqual(validate_target("rmvx", target_dir=tmp_dir), 1, "Validator must reject wrong transform policy")

        # 4. Wrong category in manifest
        with tempfile.TemporaryDirectory(prefix="val_tamper_") as tmp_dir:
            shutil.copytree(clean_dir, tmp_dir, dirs_exist_ok=True)
            mp = os.path.join(tmp_dir, "manifest.json")
            with open(mp, "r", encoding="utf-8") as f:
                d = json.load(f)
            d["entries"][0]["category"] = "ChipSet"
            with open(mp, "w", encoding="utf-8") as f:
                json.dump(d, f)
            self.assertEqual(validate_target("rmvx", target_dir=tmp_dir), 1, "Validator must reject wrong category")

        # 5. Wrong target hash in manifest
        with tempfile.TemporaryDirectory(prefix="val_tamper_") as tmp_dir:
            shutil.copytree(clean_dir, tmp_dir, dirs_exist_ok=True)
            mp = os.path.join(tmp_dir, "manifest.json")
            with open(mp, "r", encoding="utf-8") as f:
                d = json.load(f)
            d["entries"][0]["sha256"] = "0" * 64
            with open(mp, "w", encoding="utf-8") as f:
                json.dump(d, f)
            self.assertEqual(validate_target("rmvx", target_dir=tmp_dir), 1, "Validator must reject wrong target hash")

        # 6. Deliberate directional-row permutation in Actor1.png (swap row 0 DOWN with row 1 LEFT in Character 0)
        with tempfile.TemporaryDirectory(prefix="val_tamper_") as tmp_dir:
            shutil.copytree(clean_dir, tmp_dir, dirs_exist_ok=True)
            png_path = os.path.join(tmp_dir, "Graphics", "Characters", "Actor1.png")
            _, _, p_pix = decode_png_rgba(png_path)
            corrupt_pix = [list(row) for row in p_pix]
            for py in range(32):
                for px in range(72):
                    corrupt_pix[py][px], corrupt_pix[py + 32][px] = corrupt_pix[py + 32][px], corrupt_pix[py][px]
            raw_b = bytearray()
            for y in range(256):
                for x in range(288):
                    raw_b.extend(corrupt_pix[y][x])
            png_bytes = create_rgba_png(288, 256, bytes(raw_b))
            with open(png_path, "wb") as pf:
                pf.write(png_bytes)
            mp = os.path.join(tmp_dir, "manifest.json")
            with open(mp, "r", encoding="utf-8") as f:
                d = json.load(f)
            d["entries"][0]["sha256"] = compute_sha256(png_path)
            with open(mp, "w", encoding="utf-8") as f:
                json.dump(d, f)
            self.assertEqual(validate_target("rmvx", target_dir=tmp_dir), 1, "Validator must reject directional-row permutation")

    def test_11_rmvx_positive_runtime_execution(self):
        """Executes positive mkxp-z RGSS2 control in isolated temporary directory."""
        if not os.environ.get("SUPERRTP_REQUIRE_RUNTIME"):
            self.skipTest("SUPERRTP_REQUIRE_RUNTIME not set")

        mkxp_bin = shutil.which("mkxp-z") or os.path.expanduser("~/.local/bin/mkxp-z")
        if not os.path.exists(mkxp_bin):
            self.skipTest("mkxp-z binary not installed")

        fixture_dir = os.path.join(REPO_ROOT, "tests", "fixtures", "rmvx_character_min")
        target_dir = os.path.join(REPO_ROOT, "generated", "rmvx")

        with tempfile.TemporaryDirectory(prefix="test_rmvx_pos_") as tmp_dir:
            conf = {
                "rgssVersion": 2,
                "gameFolder": os.path.abspath(fixture_dir),
                "customScript": "fixture.rb",
                "pathCache": True,
                "RTP": [os.path.abspath(target_dir)]
            }
            with open(os.path.join(tmp_dir, "mkxp.json"), "w", encoding="utf-8") as f:
                json.dump(conf, f)

            cmd = (
                f"cd {tmp_dir} && "
                f"xvfb-run -a -s '-screen 0 544x416x24' bash -c '"
                f"SDL_AUDIODRIVER=dummy ALSOFT_DRIVERS=null SDL_VIDEODRIVER=x11 LIBGL_ALWAYS_SOFTWARE=1 {mkxp_bin} 2>&1'"
            )
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            self.assertEqual(res.returncode, 0, f"Positive run failed: {res.stdout}\n{res.stderr}")
            self.assertIn("SUPERRTP_RGSS2_SCREEN 544x416", res.stdout)
            self.assertIn("SUPERRTP_RMVX_CHARACTER_LOADED 288x256", res.stdout)
            self.assertIn("SUPERRTP_RMVX_RENDER_DONE", res.stdout)

    def test_12_rmvx_negative_runtime_execution(self):
        """Executes negative mkxp-z RGSS2 control and verifies specific missing asset failure."""
        if not os.environ.get("SUPERRTP_REQUIRE_RUNTIME"):
            self.skipTest("SUPERRTP_REQUIRE_RUNTIME not set")

        mkxp_bin = shutil.which("mkxp-z") or os.path.expanduser("~/.local/bin/mkxp-z")
        if not os.path.exists(mkxp_bin):
            self.skipTest("mkxp-z binary not installed")

        fixture_dir = os.path.join(REPO_ROOT, "tests", "fixtures", "rmvx_character_min")

        with tempfile.TemporaryDirectory(prefix="test_rmvx_neg_") as tmp_dir:
            conf = {
                "rgssVersion": 2,
                "gameFolder": os.path.abspath(fixture_dir),
                "customScript": "fixture.rb",
                "pathCache": True,
                "RTP": []
            }
            with open(os.path.join(tmp_dir, "mkxp.json"), "w", encoding="utf-8") as f:
                json.dump(conf, f)

            cmd = (
                f"cd {tmp_dir} && "
                f"xvfb-run -a -s '-screen 0 544x416x24' bash -c '"
                f"SDL_AUDIODRIVER=dummy ALSOFT_DRIVERS=null SDL_VIDEODRIVER=x11 LIBGL_ALWAYS_SOFTWARE=1 {mkxp_bin} 2>&1'"
            )
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            self.assertEqual(res.returncode, 1, f"Negative run expected code 1, got {res.returncode}")
            self.assertIn("SUPERRTP_RMVX_MISSING_ASSET: No such file or directory - Graphics/Characters/Actor1", res.stdout)

    def test_13_evidence_chain_integrity(self):
        """Verifies full RMVX evidence contract and hash chain."""
        cfg = get_target_config()
        self.assertTrue(verify_evidence_chain(cfg["evidence_path"], cfg))

    def test_14_adversarial_evidence_tamper_suite(self):
        """Attacks all authoritative evidence fields, sub-objects, and screenshot pixels."""
        cfg = get_target_config()
        evidence_path = cfg["evidence_path"]
        with open(evidence_path, "r", encoding="utf-8") as f:
            base_evidence = json.load(f)

        # 1. Top-level and hash field attacks
        top_tamper_attacks = [
            ("target", "rm2000", "Evidence target mismatch"),
            ("engine", "RPG Maker XP", "Evidence engine mismatch"),
            ("engine_mode", "rgss1", "Evidence engine_mode mismatch"),
            ("runtime", "easyrpg", "Evidence runtime mismatch"),
            ("runtime_commit", "0" * 40, "mkxp-z commit pin violation"),
            ("rgss_version", 1, "Evidence rgss_version mismatch"),
            ("target_category", "ChipSet", "Evidence target_category mismatch"),
            ("requested_resource", "Graphics/Characters/Actor2", "Evidence requested_resource mismatch"),
            ("source_character_indices", [0], "Evidence source_character_indices mismatch"),
            ("transform_policy", "direct_copy", "Evidence transform_policy mismatch"),
            ("canonical_asset_id", "wrong.id", "Unexpected canonical_asset_id"),
            ("canonical_source_sha256", "0" * 64, "Canonical source SHA-256 mismatch"),
            ("target_manifest_sha256", "0" * 64, "Target manifest hash mismatch"),
            ("target_character_sha256", "0" * 64, "Target character file hash mismatch"),
            ("fixture_manifest_sha256", "0" * 64, "Fixture manifest hash mismatch"),
            ("fixture_script_sha256", "0" * 64, "Fixture script hash mismatch"),
            ("positive_runtime_configuration_sha256", "0" * 64, "Positive runtime configuration hash mismatch"),
            ("negative_runtime_configuration_sha256", "0" * 64, "Negative runtime configuration hash mismatch"),
            ("positive_exit_code", 1, "positive_exit_code mismatch"),
            ("negative_exit_code", 0, "negative_exit_code mismatch"),
            ("positive_runtime_log_sha256", "0" * 64, "Positive runtime log hash mismatch"),
            ("negative_runtime_log_sha256", "0" * 64, "Negative runtime log hash mismatch"),
        ]

        for field_name, bad_value, expected_msg in top_tamper_attacks:
            corrupt = dict(base_evidence)
            corrupt[field_name] = bad_value
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as tf:
                json.dump(corrupt, tf)
                tf.flush()
                with self.assertRaises(ValueError, msg=f"Tamper on {field_name} did not fail!") as cm:
                    verify_evidence_chain(tf.name, cfg)
                self.assertIn(expected_msg, str(cm.exception), f"Wrong error message on {field_name} tamper")

        # 2. Sub-object attacks (build config, negative control, screenshots)
        nested_tamper_attacks = [
            ("mkxp_z_build_configuration", "build_config_revision", "buildcfg1", "build_config_revision mismatch"),
            ("mkxp_z_build_configuration", "workdir_current", False, "workdir_current must be true"),
            ("mkxp_z_build_configuration", "static_executable", True, "static_executable must be false"),
            ("mkxp_z_build_configuration", "shared_fluid", True, "shared_fluid must be false"),
            ("mkxp_z_build_configuration", "mri_version", "", "mri_version must be non-empty string"),
            ("negative_control", "diagnostic", "Wrong diagnostic", "negative_control.diagnostic mismatch"),
            ("negative_control", "screenshot_sha256", "0" * 64, "negative_control screenshot_sha256 mismatch"),
            ("screenshots", "rmvx_character_positive.png", "0" * 64, "SHA-256 mismatch"),
            ("screenshots", "rmvx_character_negative_control.png", "0" * 64, "negative_control screenshot_sha256 mismatch"),
        ]

        for parent, key, bad_val, exp_err in nested_tamper_attacks:
            corrupt = dict(base_evidence)
            corrupt[parent] = dict(corrupt[parent])
            corrupt[parent][key] = bad_val
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as tf:
                json.dump(corrupt, tf)
                tf.flush()
                with self.assertRaises(ValueError, msg=f"Tamper on {parent}.{key} did not fail!") as cm:
                    verify_evidence_chain(tf.name, cfg)
                self.assertIn(exp_err, str(cm.exception), f"Wrong error message on {parent}.{key} tamper")

        # 3. Screenshot pixel tampering attack
        with tempfile.TemporaryDirectory(prefix="tamper_shot_") as tmp_art_dir:
            shutil.copytree(cfg["artifacts_dir"], tmp_art_dir, dirs_exist_ok=True)
            shot_path = os.path.join(tmp_art_dir, "rmvx_character_positive.png")
            w, h, rgb_pix = decode_png_rgb(shot_path)

            # Corrupt pad TL corner marker at y=70, x=118 from red to black
            corrupt_rgba = bytearray()
            for y in range(h):
                for x in range(w):
                    r, g, b = rgb_pix[y][x]
                    if y == 70 and x == 118:
                        r, g, b = 0, 0, 0
                    corrupt_rgba.extend([r, g, b, 255])
            corrupt_png = create_rgba_png(w, h, bytes(corrupt_rgba))
            with open(shot_path, "wb") as pf:
                pf.write(corrupt_png)

            corrupt_ev = dict(base_evidence)
            corrupt_ev["screenshots"] = dict(corrupt_ev["screenshots"])
            corrupt_ev["screenshots"]["rmvx_character_positive.png"] = compute_sha256(shot_path)
            ev_path = os.path.join(tmp_art_dir, "verification_evidence.json")
            with open(ev_path, "w", encoding="utf-8") as f:
                json.dump(corrupt_ev, f)

            tmp_cfg = dict(cfg)
            tmp_cfg["artifacts_dir"] = tmp_art_dir
            tmp_cfg["evidence_path"] = ev_path
            with self.assertRaises(ValueError, msg="Corrupt screenshot pixels did not fail verification!") as cm:
                verify_evidence_chain(ev_path, tmp_cfg)
            self.assertIn("Pad TL corner marker mismatch", str(cm.exception))

if __name__ == "__main__":
    unittest.main()
