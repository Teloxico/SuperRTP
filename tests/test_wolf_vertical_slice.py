#!/usr/bin/env python3
"""
Comprehensive Automated Test Suite for SuperRTP Phase 1 Task 7:
WOLF RPG Editor v3 Character / CharaChip Compatibility Slice.
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

from transforms import (
    extract_walking_frames,
    pack_wolf_character,
    transform_canonical_to_wolf_character,
    pack_rmvx_character_sheet,
    pack_rmvxace_character_sheet
)
from build_target import build_target
from validate_target import validate_target, validate_png_wolf_character
from png_utils import decode_png_rgb, decode_png_rgba, create_rgba_png
from schema_validator import validate_schema
from verify_wolf_runtime import verify_wolf_screenshot, check_evidence_file

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

    frame_bytes = bytearray()
    for py in range(32):
        y = frame_y + py
        start_idx = (y * 288 + frame_x) * 4
        end_idx = start_idx + 24 * 4
        frame_bytes.extend(raw_rgba[start_idx:end_idx])

    return bytes(frame_bytes)

class TestWolfVerticalSlice(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.canonical_rgba_path = os.path.join(
            REPO_ROOT, "registry", "assets", "test_calibration_walking_character.rgba"
        )
        with open(cls.canonical_rgba_path, "rb") as f:
            cls.canonical_rgba = f.read()

        cls.expected_canonical_sha256 = "78ad9a170ac0ba06eb4756f9c9c19923e754e82c22025dab7dfbc46de5c1b790"
        cls.expected_wolf_char_sha256 = "da3f32ef170575ff49abb04197413b663b1010735154ac2435771eeab02dc6e7"
        cls.expected_rmvx_char_sha256 = "c6ed8cba9025b982c6300ed5e57a82aee99cc29f7929d81cf1b517ded47550bf"
        cls.expected_rmvxace_char_sha256 = "c6ed8cba9025b982c6300ed5e57a82aee99cc29f7929d81cf1b517ded47550bf"

    def test_01_canonical_asset_integrity(self):
        """Asserts that the clean-room canonical walking-character asset hash is strictly preserved."""
        actual_sha = hashlib.sha256(self.canonical_rgba).hexdigest()
        self.assertEqual(actual_sha, self.expected_canonical_sha256)
        self.assertEqual(len(self.canonical_rgba), 288 * 256 * 4)

    def test_02_semantic_walking_frame_extraction_char0(self):
        """
        Asserts semantic frame extraction for character index 0 against
        the independent physical crop oracle for all 12 cells (4 directions x 3 phases).
        """
        directions = ("DOWN", "LEFT", "RIGHT", "UP")
        phases = ("STEP_LEFT", "IDLE", "STEP_RIGHT")

        char_frames = extract_walking_frames(self.canonical_rgba, char_idx=0)
        for d in directions:
            for p in phases:
                extracted = char_frames[d][p]
                oracle = crop_physical_source_frame(self.canonical_rgba, 0, d, p)
                self.assertEqual(
                    extracted,
                    oracle,
                    f"Mismatch in extracted frame for Char 0, Direction {d}, Phase {p}"
                )
                self.assertEqual(len(extracted), 24 * 32 * 4)

    def test_03_wolf_packer_output_structure(self):
        """
        Asserts that pack_wolf_character produces a valid 72x128 32-bit truecolor RGBA PNG
        matching the frozen SHA-256 and containing no palette or transparency chunks.
        """
        char_frames = extract_walking_frames(self.canonical_rgba, char_idx=0)
        png_bytes = pack_wolf_character(char_frames)

        # Hash check
        actual_sha = hashlib.sha256(png_bytes).hexdigest()
        self.assertEqual(actual_sha, self.expected_wolf_char_sha256)

        # PNG structure checks
        self.assertTrue(png_bytes.startswith(b"\x89PNG\r\n\x1a\n"))

        # Chunk inspection
        offset = 8
        found_chunks = []
        ihdr_seen = False
        while offset < len(png_bytes):
            length = struct.unpack(">I", png_bytes[offset:offset+4])[0]
            chunk_type = png_bytes[offset+4:offset+8].decode("ascii", errors="replace")
            found_chunks.append(chunk_type)
            if chunk_type == "IHDR":
                ihdr_seen = True
                w, h, bit_depth, color_type = struct.unpack(">IIBB", png_bytes[offset+8:offset+18])
                self.assertEqual(w, 72)
                self.assertEqual(h, 128)
                self.assertEqual(bit_depth, 8)
                self.assertEqual(color_type, 6)  # RGBA
            offset += 12 + length

        self.assertTrue(ihdr_seen)
        self.assertNotIn("PLTE", found_chunks)
        self.assertNotIn("tRNS", found_chunks)
        self.assertIn("IDAT", found_chunks)
        self.assertIn("IEND", found_chunks)

    def test_04_wolf_slot_registry_and_schema_validation(self):
        """Validates registry/slots/wolf.json against schemas/slot_mapping.schema.json."""
        slot_file = os.path.join(REPO_ROOT, "registry", "slots", "wolf.json")
        self.assertTrue(os.path.exists(slot_file))

        schema_file = os.path.join(REPO_ROOT, "schemas", "slot_mapping.schema.json")
        self.assertTrue(os.path.exists(schema_file))

        with open(slot_file, "r", encoding="utf-8") as f:
            slot_data = json.load(f)
        with open(schema_file, "r", encoding="utf-8") as f:
            schema_data = json.load(f)

        # Validate schema using project schema_validator
        validate_schema(slot_data, schema_data)

        self.assertEqual(slot_data["target"], "wolf")
        self.assertEqual(slot_data["engine"], "WOLF RPG Editor")
        self.assertEqual(len(slot_data["slots"]), 1)
        self.assertIn("Data/CharaChip/SuperRTP_Calibration.png", slot_data["slots"])

        slot = slot_data["slots"]["Data/CharaChip/SuperRTP_Calibration.png"]
        self.assertEqual(slot["slot_path"], "Data/CharaChip/SuperRTP_Calibration.png")
        self.assertEqual(slot["category"], "Character")
        self.assertEqual(slot["direction_mode"], 4)
        self.assertEqual(slot["animation_patterns"], 3)
        self.assertEqual(slot["runtime_reference"], "CharaChip/SuperRTP_Calibration.png")
        self.assertEqual(slot["character_index"], 0)
        self.assertEqual(slot["transform_policy"], "rm2k_char0_to_wolf3_p3_d4_character_v1")

    def test_05_wolf_target_validation(self):
        """Asserts that validate_png_wolf_character and validate_target('wolf') pass cleanly."""
        target_png = os.path.join(REPO_ROOT, "generated", "wolf", "Data", "CharaChip", "SuperRTP_Calibration.png")
        self.assertTrue(os.path.exists(target_png))

        validate_png_wolf_character(target_png)
        self.assertEqual(validate_target("wolf"), 0)

    def test_06_twelve_cell_exact_match_against_canonical_oracle(self):
        """
        Decodes the generated WOLF CharaChip and verifies every single 24x32 cell
        against direct physical crops from the canonical walking-character asset.
        """
        target_png = os.path.join(REPO_ROOT, "generated", "wolf", "Data", "CharaChip", "SuperRTP_Calibration.png")
        w, h, wolf_pixels = decode_png_rgba(target_png)
        self.assertEqual(w, 72)
        self.assertEqual(h, 128)

        wolf_row_dirs = ["DOWN", "LEFT", "RIGHT", "UP"]
        wolf_col_phases = ["STEP_LEFT", "IDLE", "STEP_RIGHT"]

        for row_idx, direction in enumerate(wolf_row_dirs):
            for col_idx, phase in enumerate(wolf_col_phases):
                oracle_frame = crop_physical_source_frame(self.canonical_rgba, 0, direction, phase)

                # Extract 24x32 cell from decoded wolf_pixels
                cell_bytes = bytearray()
                for py in range(32):
                    for px in range(24):
                        cell_bytes.extend(wolf_pixels[row_idx * 32 + py][col_idx * 24 + px])

                self.assertEqual(
                    bytes(cell_bytes),
                    oracle_frame,
                    f"Pixel mismatch in WOLF CharaChip cell at row {row_idx} ({direction}), col {col_idx} ({phase})"
                )

    def test_07_cross_target_pixel_equality_with_rmvx_and_rmvxace(self):
        """
        Verifies architectural cross-target invariant:
        Decoded WOLF 72x128 CharaChip pixels are 100% byte-identical to the top-left
        72x128 region of both RMVX and RMVXAce Actor1.png character sheets.
        """
        wolf_png = os.path.join(REPO_ROOT, "generated", "wolf", "Data", "CharaChip", "SuperRTP_Calibration.png")
        rmvx_png = os.path.join(REPO_ROOT, "generated", "rmvx", "Graphics", "Characters", "Actor1.png")
        rmvxace_png = os.path.join(REPO_ROOT, "generated", "rmvxace", "Graphics", "Characters", "Actor1.png")

        self.assertTrue(os.path.exists(wolf_png))
        self.assertTrue(os.path.exists(rmvx_png))
        self.assertTrue(os.path.exists(rmvxace_png))

        ww, wh, wolf_pixels = decode_png_rgba(wolf_png)
        vxw, vxh, rmvx_pixels = decode_png_rgba(rmvx_png)
        acew, aceh, rmvxace_pixels = decode_png_rgba(rmvxace_png)

        self.assertEqual((ww, wh), (72, 128))
        self.assertEqual((vxw, vxh), (288, 256))
        self.assertEqual((acew, aceh), (288, 256))

        # Crop top-left 72x128 from RMVX and RMVXAce
        wolf_flat = bytearray()
        rmvx_char0 = bytearray()
        rmvxace_char0 = bytearray()
        for y in range(128):
            for x in range(72):
                wolf_flat.extend(wolf_pixels[y][x])
                rmvx_char0.extend(rmvx_pixels[y][x])
                rmvxace_char0.extend(rmvxace_pixels[y][x])

        self.assertEqual(bytes(wolf_flat), bytes(rmvx_char0), "WOLF CharaChip != RMVX Char 0 crop")
        self.assertEqual(bytes(wolf_flat), bytes(rmvxace_char0), "WOLF CharaChip != RMVXAce Char 0 crop")

    def test_08_cross_target_cell_equality_with_rmxp(self):
        """
        Verifies architectural cross-target invariant with RMXP:
        The 12 cells of WOLF CharaChip match the 4 directions x 3 unique walking frames
        of RMXP 001-Fighter01.png (excluding RMXP's 4th repeated column).
        """
        wolf_png = os.path.join(REPO_ROOT, "generated", "wolf", "Data", "CharaChip", "SuperRTP_Calibration.png")
        rmxp_png = os.path.join(REPO_ROOT, "generated", "rmxp", "Graphics", "Characters", "001-Fighter01.png")

        ww, wh, wolf_pixels = decode_png_rgba(wolf_png)
        xpw, xph, rmxp_pixels = decode_png_rgba(rmxp_png)

        self.assertEqual((ww, wh), (72, 128))
        self.assertEqual((xpw, xph), (96, 128))

        # Check each direction (rows 0..3) and phases (cols 0..2)
        for r in range(4):
            for c in range(3):
                wolf_cell = bytearray()
                rmxp_cell = bytearray()
                for py in range(32):
                    for px in range(24):
                        wolf_cell.extend(wolf_pixels[r * 32 + py][c * 24 + px])
                        rmxp_cell.extend(rmxp_pixels[r * 32 + py][c * 24 + px])

                self.assertEqual(
                    bytes(wolf_cell),
                    bytes(rmxp_cell),
                    f"WOLF cell at row {r}, col {c} != RMXP cell at row {r}, col {c}"
                )

    def test_09_deterministic_ab_rebuild(self):
        """Asserts that building the wolf target twice in isolated directories is 100% byte-identical."""
        with tempfile.TemporaryDirectory(prefix="wolf_rebuild_a_") as tda, \
             tempfile.TemporaryDirectory(prefix="wolf_rebuild_b_") as tdb:

            build_target("wolf", output_dir=tda)
            build_target("wolf", output_dir=tdb)

            file_a = os.path.join(tda, "Data", "CharaChip", "SuperRTP_Calibration.png")
            file_b = os.path.join(tdb, "Data", "CharaChip", "SuperRTP_Calibration.png")
            manifest_a = os.path.join(tda, "manifest.json")
            manifest_b = os.path.join(tdb, "manifest.json")

            with open(file_a, "rb") as fa, open(file_b, "rb") as fb:
                self.assertEqual(fa.read(), fb.read())
            with open(manifest_a, "rb") as ma, open(manifest_b, "rb") as mb:
                self.assertEqual(ma.read(), mb.read())

            self.assertEqual(compute_sha256(file_a), self.expected_wolf_char_sha256)

    def test_10_frozen_baseline_golden_hashes(self):
        """Asserts that all accepted golden hashes from Tasks 1-6 remain strictly preserved."""
        golden_hashes = {
            "Canonical CharSet": (
                os.path.join(REPO_ROOT, "registry", "assets", "test_calibration_walking_character.rgba"),
                "78ad9a170ac0ba06eb4756f9c9c19923e754e82c22025dab7dfbc46de5c1b790"
            ),
            "Canonical ChipSet": (
                os.path.join(REPO_ROOT, "registry", "assets", "test_calibration_map_chipset.rgba"),
                "4a4f5bdf6dbbbd12b23e358d1780eb8c3163ac81b25f4b2e3b366f50ab54454f"
            ),
            "RM2000 Actor1": (
                os.path.join(REPO_ROOT, "generated", "rm2000", "CharSet", "Actor1.png"),
                "7fde5157142d929404f3fc3b599cbd6c558ef74b2135ac1172db53dd88641ee6"
            ),
            "RM2003 Actor1": (
                os.path.join(REPO_ROOT, "generated", "rm2003", "CharSet", "Actor1.png"),
                "7fde5157142d929404f3fc3b599cbd6c558ef74b2135ac1172db53dd88641ee6"
            ),
            "RM2000 Basis": (
                os.path.join(REPO_ROOT, "generated", "rm2000", "ChipSet", "Basis.png"),
                "8a1c5552c544fb5195a92ab8f2f0e84b11d95fa3929250aa74b69630067fe137"
            ),
            "RM2003 Main": (
                os.path.join(REPO_ROOT, "generated", "rm2003", "ChipSet", "Main.png"),
                "8a1c5552c544fb5195a92ab8f2f0e84b11d95fa3929250aa74b69630067fe137"
            ),
            "RMXP 001-Fighter01": (
                os.path.join(REPO_ROOT, "generated", "rmxp", "Graphics", "Characters", "001-Fighter01.png"),
                "b4e81694247632b5580b5eef55a17e61c6afd709092de0e574aed70b41759743"
            ),
            "RMVX Actor1": (
                os.path.join(REPO_ROOT, "generated", "rmvx", "Graphics", "Characters", "Actor1.png"),
                "c6ed8cba9025b982c6300ed5e57a82aee99cc29f7929d81cf1b517ded47550bf"
            ),
            "RMVXAce Actor1": (
                os.path.join(REPO_ROOT, "generated", "rmvxace", "Graphics", "Characters", "Actor1.png"),
                "c6ed8cba9025b982c6300ed5e57a82aee99cc29f7929d81cf1b517ded47550bf"
            ),
            "WOLF SuperRTP_Calibration": (
                os.path.join(REPO_ROOT, "generated", "wolf", "Data", "CharaChip", "SuperRTP_Calibration.png"),
                "da3f32ef170575ff49abb04197413b663b1010735154ac2435771eeab02dc6e7"
            )
        }

        for name, (path, expected_hash) in golden_hashes.items():
            self.assertTrue(os.path.exists(path), f"Asset {name} not found at {path}")
            actual_hash = compute_sha256(path)
            self.assertEqual(actual_hash, expected_hash, f"Golden hash regression for {name}")

    def test_11_clean_room_fixture_integrity(self):
        """Verifies clean-room WOLF fixture integrity and hash-bound manifest."""
        fixture_dir = os.path.join(REPO_ROOT, "tests", "fixtures", "wolf_character_min")
        self.assertTrue(os.path.exists(fixture_dir))

        manifest_path = os.path.join(fixture_dir, "fixture_manifest.json")
        self.assertTrue(os.path.exists(manifest_path))

        with open(manifest_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        self.assertEqual(meta["engine"], "WOLF RPG Editor")
        self.assertEqual(meta["version"], "3.717")
        self.assertIn("clean_room_attestation", meta)

        # Verify project data hashes
        for filename, fileinfo in meta["project_data"].items():
            filepath = os.path.join(fixture_dir, filename)
            self.assertTrue(os.path.exists(filepath), f"Missing fixture file: {filename}")
            self.assertEqual(compute_sha256(filepath), fileinfo["sha256"])

        # Verify support asset hashes
        for filename, fileinfo in meta["support_assets"].items():
            filepath = os.path.join(fixture_dir, filename)
            self.assertTrue(os.path.exists(filepath), f"Missing support asset: {filename}")
            self.assertEqual(compute_sha256(filepath), fileinfo["sha256"])

        # Verify Game.dat bytes 17=0 and 20=0
        game_dat_path = os.path.join(fixture_dir, "Data", "BasicData", "Game.dat")
        with open(game_dat_path, "rb") as f:
            gdat = f.read()
        self.assertEqual(gdat[17], 0, "Game.dat byte 17 must be 0")
        self.assertEqual(gdat[20], 0, "Game.dat byte 20 must be 0")

    def test_12_adversarial_tamper_suite(self):
        """Tests that validate_target rejects corrupted, incorrectly dimensioned, or permuted PNGs."""
        # 1. Dimension mismatch
        with tempfile.TemporaryDirectory() as td:
            build_target("wolf", output_dir=td)
            bad_png = os.path.join(td, "Data", "CharaChip", "SuperRTP_Calibration.png")
            # Write 72x120 instead of 72x128
            fake_rgba = bytearray(72 * 120 * 4)
            fake_png = create_rgba_png(72, 120, bytes(fake_rgba))
            with open(bad_png, "wb") as f:
                f.write(fake_png)
            self.assertEqual(validate_target("wolf", target_dir=td), 1)

        # 2. Corrupted PNG header
        with tempfile.TemporaryDirectory() as td:
            build_target("wolf", output_dir=td)
            bad_png = os.path.join(td, "Data", "CharaChip", "SuperRTP_Calibration.png")
            with open(bad_png, "wb") as f:
                f.write(b"NOT_A_PNG_FILE")
            self.assertEqual(validate_target("wolf", target_dir=td), 1)

        # 3. Missing file
        with tempfile.TemporaryDirectory() as td:
            build_target("wolf", output_dir=td)
            bad_png = os.path.join(td, "Data", "CharaChip", "SuperRTP_Calibration.png")
            os.remove(bad_png)
            self.assertEqual(validate_target("wolf", target_dir=td), 1)

        # 4. Swapped directional rows (DOWN and UP swapped)
        with tempfile.TemporaryDirectory() as td:
            build_target("wolf", output_dir=td)
            bad_png = os.path.join(td, "Data", "CharaChip", "SuperRTP_Calibration.png")
            w, h, pixels = decode_png_rgba(bad_png)
            # Flatten pixels
            flat = bytearray()
            for r in pixels:
                for px in r:
                    flat.extend(px)
            # Swap row 0 (DOWN) and row 3 (UP)
            swapped = bytearray(flat)
            row_size = 72 * 32 * 4
            swapped[:row_size] = flat[3 * row_size: 4 * row_size]
            swapped[3 * row_size: 4 * row_size] = flat[:row_size]
            with open(bad_png, "wb") as f:
                f.write(create_rgba_png(72, 128, bytes(swapped)))
            self.assertEqual(validate_target("wolf", target_dir=td), 1)

    def test_13_durable_runtime_evidence_chain(self):
        """Verifies the complete durable evidence chain for wolf Character compatibility."""
        evidence_file = os.path.join(
            REPO_ROOT, "artifacts", "runtime", "wolf", "character", "verification_evidence.json"
        )
        self.assertTrue(os.path.exists(evidence_file), f"Evidence file not found: {evidence_file}")
        res = check_evidence_file(evidence_file)
        self.assertEqual(res, 0, "Evidence file verification failed")

    def test_14_adversarial_runtime_verifier_rejection(self):
        """
        Adversarially tests that runtime verifiers reject fabricated lookup,
        swapped directional orientations, corrupted animation phases, and tampered error controls.
        """
        artifacts_dir = os.path.join(REPO_ROOT, "artifacts", "runtime", "wolf", "character")
        target_char_path = os.path.join(REPO_ROOT, "generated", "wolf", "Data", "CharaChip", "SuperRTP_Calibration.png")

        # 1. Dynamic lookup tampering in positive screenshot: erase OCR text area
        pos_path = os.path.join(artifacts_dir, "wolf_character_positive.png")
        w, h, pos_rgb = decode_png_rgb(pos_path)
        bad_pos_rgb = [list(r) for r in pos_rgb]
        # Overwrite lines 380..479 with black
        for y in range(380, 480):
            for x in range(200):
                bad_pos_rgb[y][x] = (0, 0, 0)
        with tempfile.TemporaryDirectory() as td:
            bad_pos_path = os.path.join(td, "bad_pos.png")
            flat_bytes = bytearray()
            for row in bad_pos_rgb:
                for r, g, b in row:
                    flat_bytes.extend((r, g, b, 255))
            with open(bad_pos_path, "wb") as f:
                f.write(create_rgba_png(w, h, bytes(flat_bytes)))
            with self.assertRaises(ValueError) as ctx:
                verify_wolf_screenshot(bad_pos_path, target_char_path=target_char_path, mode="positive")
            self.assertIn("Extracted lookup dimensions mismatch", str(ctx.exception))

        # 2. Tampered lookup result in evidence JSON
        evidence_file = os.path.join(artifacts_dir, "verification_evidence.json")
        with open(evidence_file, "r", encoding="utf-8") as f:
            ev_data = json.load(f)
        bad_ev = dict(ev_data)
        bad_ev["positive_lookup_result"] = "64 128"
        with tempfile.TemporaryDirectory() as td:
            bad_ev_path = os.path.join(td, "bad_ev.json")
            with open(bad_ev_path, "w", encoding="utf-8") as f:
                json.dump(bad_ev, f)
            with self.assertRaises(ValueError) as ctx:
                check_evidence_file(bad_ev_path)
            self.assertIn("Positive lookup result mismatch", str(ctx.exception))

        # 3. Directional map-event tampering: Down arrow tested against Up arrow pattern (11)
        down_path = os.path.join(artifacts_dir, "wolf_character_down.png")
        with self.assertRaises(ValueError) as ctx:
            verify_wolf_screenshot(down_path, target_char_path=target_char_path, mode="directional", expected_pat=11)
        self.assertIn("not found in directional screenshot", str(ctx.exception))

        # 4. Directional tampering: erase character in wolf_character_down.png
        w, h, down_rgb = decode_png_rgb(down_path)
        bad_down_rgb = [list(r) for r in down_rgb]
        for y in range(160, 224):
            for x in range(280, 328):
                bad_down_rgb[y][x] = (0, 0, 0)
        with tempfile.TemporaryDirectory() as td:
            bad_down_path = os.path.join(td, "bad_down.png")
            flat_bytes = bytearray()
            for row in bad_down_rgb:
                for r, g, b in row:
                    flat_bytes.extend((r, g, b, 255))
            with open(bad_down_path, "wb") as f:
                f.write(create_rgba_png(w, h, bytes(flat_bytes)))
            with self.assertRaises(ValueError) as ctx:
                verify_wolf_screenshot(bad_down_path, target_char_path=target_char_path, mode="directional", expected_pat=2)
            self.assertIn("not found in directional screenshot", str(ctx.exception))

        # 5. Animation phase tampering: StepLeft screenshot tested against Idle pattern (2)
        step1_path = os.path.join(artifacts_dir, "wolf_character_walk_step1.png")
        with self.assertRaises(ValueError) as ctx:
            verify_wolf_screenshot(step1_path, target_char_path=target_char_path, mode="directional", expected_pat=2)
        self.assertTrue("not found in directional screenshot" in str(ctx.exception) or "Transparent pixel did not expose black background" in str(ctx.exception) or "Pixel mismatch in directional shot" in str(ctx.exception))

        # 6. Negative control tampering: erase error banner in negative control screenshot
        neg_path = os.path.join(artifacts_dir, "wolf_character_negative_control.png")
        w, h, neg_rgb = decode_png_rgb(neg_path)
        bad_neg_rgb = [[(0, 0, 0) for _ in range(w)] for _ in range(h)]
        with tempfile.TemporaryDirectory() as td:
            bad_neg_path = os.path.join(td, "bad_neg.png")
            flat_bytes = bytearray()
            for row in bad_neg_rgb:
                for r, g, b in row:
                    flat_bytes.extend((r, g, b, 255))
            with open(bad_neg_path, "wb") as f:
                f.write(create_rgba_png(w, h, bytes(flat_bytes)))
            with self.assertRaises(ValueError) as ctx:
                verify_wolf_screenshot(bad_neg_path, mode="negative_control")
            self.assertIn("Negative control missing green error banner", str(ctx.exception))

        # 7. Missing Game_ErrorLog.txt check in evidence chain
        with tempfile.TemporaryDirectory() as td:
            for item in os.listdir(artifacts_dir):
                if item != "Game_ErrorLog.txt":
                    shutil.copy2(os.path.join(artifacts_dir, item), os.path.join(td, item))
            from verify_wolf_runtime import get_target_config, verify_evidence_chain
            custom_cfg = get_target_config()
            custom_cfg["artifacts_dir"] = td
            with self.assertRaises(FileNotFoundError) as ctx:
                verify_evidence_chain(os.path.join(td, "verification_evidence.json"), cfg=custom_cfg)
            self.assertIn("Game_ErrorLog.txt", str(ctx.exception))

if __name__ == "__main__":
    unittest.main()
