#!/usr/bin/env python3
"""
Automated Test Suite for SuperRTP Phase 1 Vertical Slice.

Tests:
  1. Canonical asset generation & deterministic reproducibility (raw RGBA + master PNG preview)
  2. PNG structure & RM2000 CharSet compliance (288x256, 8-bit indexed, index 0 transparent)
  3. Clean-room provenance attestation & source-type-aware validation
  4. Target builder, byte-for-byte reproducibility across runs, and slot alias correctness
  5. Target validator positive verification & rejection of corrupted/invalid assets
  6. Schema validation using schema_validator (assets & provenance conditional rules)
  7. Clean-room fixture manifest & programmatic graphics generator integrity
  8. Real EasyRPG Player headless RTP resolution (positive control, clean logs)
  9. Real EasyRPG Player missing-asset fallback (negative control, exact failure isolation)
  10. Four-direction runtime verification evidence chain & directional pixel assertions (RM2000)
  11. Sprite arrow shape orientation and directional asymmetry verification (RM2000)
  12. RM2003 target builder, cross-target byte determinism with RM2000, and Hero1 alias inclusion
  13. RM2003 clean-room test fixture manifest & programmatic graphics integrity
  14. Real EasyRPG Player headless RM2003 RTP resolution (positive control, clean logs)
  15. Real EasyRPG Player headless RM2003 missing-asset fallback (negative control, exact failure isolation)
  16. RM2003 four-direction runtime verification evidence chain & directional arrow assertions
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
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

from generate_calibration_charset import generate_calibration_charset
from build_target import build_target, compute_sha256, create_indexed_png as create_png
from validate_target import validate_png_charset, validate_provenance, validate_target
from schema_validator import validate_schema, SchemaValidationError
from generate_fixture_graphics import generate_minimal_chipset, generate_minimal_system
from verify_runtime import verify_evidence_chain, run_replay_and_record, verify_directional_screenshot

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

        master_png_path = os.path.join(REPO_ROOT, "registry", "assets", "test_calibration_walking_character_master.png")
        self.assertTrue(os.path.exists(master_png_path), f"Master preview PNG not found at {master_png_path}")
        self.assertEqual(compute_sha256(master_png_path), hashlib.sha256(png1).hexdigest(), "Master preview PNG hash mismatch")

        with open(os.path.join(REPO_ROOT, "registry", "assets", "test_calibration_walking_character.json"), "r") as f:
            meta = json.load(f)
        self.assertEqual(meta["sha256"], compute_sha256(rgba_path))

    def test_02_png_structural_compliance(self):
        """Verify built target PNG conforms to strict RM2000 CharSet specification."""
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
        """Verify clean-room attestations and source-type-aware validation."""
        rgba_path = os.path.join(REPO_ROOT, "registry", "assets", "test_calibration_walking_character.rgba")
        sha256 = compute_sha256(rgba_path)
        prov = validate_provenance(REPO_ROOT, "test.calibration.walking-character", sha256)

        self.assertEqual(prov["source_type"], "project_synthetic")
        self.assertTrue(prov.get("creation_tool"))
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
        """Verify JSON schemas and registry instances validate cleanly, including source-type rules."""
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

        # 1. Valid instances must pass
        validate_schema(asset_inst, asset_schema)
        validate_schema(prov_inst, prov_schema)

        # 2. Invalid provenance clean-room attestation must fail
        bad_prov = json.loads(json.dumps(prov_inst))
        bad_prov["clean_room_attestation"]["proprietary_rtp_derived"] = True
        with self.assertRaises((ValueError, SchemaValidationError)):
            validate_schema(bad_prov, prov_schema)

        # 3. project_synthetic missing creation_tool must fail
        bad_synth = json.loads(json.dumps(prov_inst))
        del bad_synth["creation_tool"]
        with self.assertRaises((ValueError, SchemaValidationError)):
            validate_schema(bad_synth, prov_schema)

        # 4. externally_licensed missing upstream_source must fail
        ext_prov = json.loads(json.dumps(prov_inst))
        ext_prov["source_type"] = "externally_licensed"
        ext_prov["license"] = "CC-BY-4.0"
        with self.assertRaises((ValueError, SchemaValidationError)):
            validate_schema(ext_prov, prov_schema)

        # 5. Valid externally_licensed record must pass
        ext_prov["upstream_source"] = {
            "author": "OpenGameArt Contributor",
            "url": "https://opengameart.org/content/example",
            "license_evidence": "CC-BY-4.0 license grant"
        }
        validate_schema(ext_prov, prov_schema)

        # 6. ai_generated missing generation_metadata must fail
        ai_prov = json.loads(json.dumps(prov_inst))
        ai_prov["source_type"] = "ai_generated"
        with self.assertRaises((ValueError, SchemaValidationError)):
            validate_schema(ai_prov, prov_schema)

        # 7. Valid ai_generated record must pass
        ai_prov["generation_metadata"] = {
            "model": "SDXL-Turbo",
            "provider": "Local",
            "prompt": "pixel art character walking",
            "parameters": {"steps": 20, "seed": 42},
            "date": "2026-09-14"
        }
        validate_schema(ai_prov, prov_schema)

    def test_07_clean_room_fixture_manifest_integrity(self):
        """Verify clean-room test fixture binaries, source generators, and programmatic graphics match manifest."""
        manifest_path = os.path.join(REPO_ROOT, "tests", "fixtures", "rm2000_min", "fixture_manifest.json")
        self.assertTrue(os.path.exists(manifest_path), "Fixture manifest must exist")
        with open(manifest_path, "r") as f:
            manifest = json.load(f)

        fixture_dir = os.path.dirname(manifest_path)

        # Check C++ LCF generator source
        gen_cpp_path = os.path.join(REPO_ROOT, manifest["generator_source"])
        self.assertEqual(compute_sha256(gen_cpp_path), manifest["generator_sha256"], "Generator C++ source modified")

        # Check Python graphics generator source
        gen_py_path = os.path.join(REPO_ROOT, manifest["graphics_generator_source"])
        self.assertEqual(compute_sha256(gen_py_path), manifest["graphics_generator_sha256"], "Graphics generator script modified")

        # Verify programmatic regeneration of ChipSet and System reproduces exact pinned hashes
        chipset_png_bytes = generate_minimal_chipset()
        system_png_bytes = generate_minimal_system()
        self.assertEqual(hashlib.sha256(chipset_png_bytes).hexdigest(), manifest["files"]["ChipSet/ChipSet.png"])
        self.assertEqual(hashlib.sha256(system_png_bytes).hexdigest(), manifest["files"]["System/System.png"])

        # Check each fixture file on disk
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

    def test_10_directional_runtime_evidence_chain(self):
        """Verify durable runtime verification evidence chain, hashes, and directional pixel assertions."""
        if os.environ.get("SUPERRTP_RUN_REPLAY") == "1":
            run_replay_and_record()

        # Check evidence chain and directional visual assertions
        self.assertTrue(verify_evidence_chain(), "Runtime verification evidence chain validation failed")

    def test_11_sprite_shape_orientation_and_evidence_hardening(self):
        """Verify directional arrow shape orientation checks and closed Actor1.png evidence validation."""
        artifact_dir = os.path.join(REPO_ROOT, "artifacts", "runtime", "rm2000", "charset")

        # 1. Verify correct shape orientation passes on genuine artifacts
        down_res = verify_directional_screenshot(os.path.join(artifact_dir, "rm2000_charset_down.png"), "down")
        self.assertEqual(down_res["status"], "VERIFIED")
        self.assertGreater(down_res["shape_metrics"]["top_w"], down_res["shape_metrics"]["bot_w"])

        up_res = verify_directional_screenshot(os.path.join(artifact_dir, "rm2000_charset_up.png"), "up")
        self.assertEqual(up_res["status"], "VERIFIED")
        self.assertLess(up_res["shape_metrics"]["top_w"], up_res["shape_metrics"]["bot_w"])

        left_res = verify_directional_screenshot(os.path.join(artifact_dir, "rm2000_charset_left.png"), "left")
        self.assertEqual(left_res["status"], "VERIFIED")
        self.assertLess(left_res["shape_metrics"]["left_h"], left_res["shape_metrics"]["right_h"])

        right_res = verify_directional_screenshot(os.path.join(artifact_dir, "rm2000_charset_right.png"), "right")
        self.assertEqual(right_res["status"], "VERIFIED")
        self.assertGreater(right_res["shape_metrics"]["left_h"], right_res["shape_metrics"]["right_h"])

        # 2. Adversarial test: verify that swapped/inverted arrow expectations are strictly rejected
        with self.assertRaises(ValueError):
            # Checking UP screenshot with DOWN expectation must fail on position or shape
            verify_directional_screenshot(os.path.join(artifact_dir, "rm2000_charset_up.png"), "down")

        with self.assertRaises(ValueError):
            # Checking LEFT screenshot with RIGHT expectation must fail
            verify_directional_screenshot(os.path.join(artifact_dir, "rm2000_charset_left.png"), "right")

    def test_12_rm2003_target_builder_and_cross_target_determinism(self):
        """Verify RM2003 builds deterministically, shares identical Actor1.png with RM2000, and includes Hero1 alias."""
        temp_dir_2k = tempfile.mkdtemp(prefix="superrtp_build2k_")
        temp_dir_2k3 = tempfile.mkdtemp(prefix="superrtp_build2k3_")
        try:
            build_target("rm2000", output_dir=temp_dir_2k, clean=True, timestamp=0)
            build_target("rm2003", output_dir=temp_dir_2k3, clean=True, timestamp=0)

            # 1. Primary Actor1.png must be byte-for-byte identical across RM2000 and RM2003 targets
            p2k_actor1 = os.path.join(temp_dir_2k, "CharSet", "Actor1.png")
            p2k3_actor1 = os.path.join(temp_dir_2k3, "CharSet", "Actor1.png")
            self.assertEqual(compute_sha256(p2k_actor1), compute_sha256(p2k3_actor1),
                             "Actor1.png must be byte-identical between RM2000 and RM2003 builds")

            # 2. Check RM2003-specific aliases: Hero1 must exist in RM2003 but not in RM2000
            self.assertTrue(os.path.exists(os.path.join(temp_dir_2k3, "CharSet", "Hero1.png")),
                            "RM2003 must contain Hero1.png")
            self.assertFalse(os.path.exists(os.path.join(temp_dir_2k, "CharSet", "Hero1.png")),
                             "RM2000 must NOT contain Hero1.png")

            # 3. Check RM2003 manifest entries
            manifest_path = os.path.join(temp_dir_2k3, "manifest.json")
            with open(manifest_path, "r") as f:
                manifest = json.load(f)
            self.assertEqual(manifest["target"], "rm2003")
            entries = {e["slot"]: e for e in manifest["entries"]}
            self.assertIn("CharSet/Hero1.png", entries)
            self.assertFalse(entries["CharSet/Hero1.png"]["is_primary"])
            self.assertEqual(entries["CharSet/Hero1.png"]["primary_slot"], "CharSet/Actor1.png")

            # 4. Target validator passes on RM2003
            exit_code = validate_target("rm2003", target_dir=temp_dir_2k3)
            self.assertEqual(exit_code, 0)
        finally:
            shutil.rmtree(temp_dir_2k, ignore_errors=True)
            shutil.rmtree(temp_dir_2k3, ignore_errors=True)

    def test_13_rm2003_clean_room_fixture_integrity(self):
        """Verify RM2003 clean-room test fixture binaries, source generators, and programmatic graphics match manifest."""
        manifest_path = os.path.join(REPO_ROOT, "tests", "fixtures", "rm2003_min", "fixture_manifest.json")
        self.assertTrue(os.path.exists(manifest_path), "RM2003 fixture manifest must exist")
        with open(manifest_path, "r") as f:
            manifest = json.load(f)

        fixture_dir = os.path.dirname(manifest_path)

        # Check generator sources
        gen_cpp_path = os.path.join(REPO_ROOT, manifest["generator_source"])
        self.assertEqual(compute_sha256(gen_cpp_path), manifest["generator_sha256"], "Generator C++ source modified")
        gen_py_path = os.path.join(REPO_ROOT, manifest["graphics_generator_source"])
        self.assertEqual(compute_sha256(gen_py_path), manifest["graphics_generator_sha256"], "Graphics generator script modified")

        # Verify programmatic regeneration of ChipSet and System reproduces exact pinned hashes
        chipset_png_bytes = generate_minimal_chipset()
        system_png_bytes = generate_minimal_system()
        self.assertEqual(hashlib.sha256(chipset_png_bytes).hexdigest(), manifest["files"]["ChipSet/ChipSet.png"])
        self.assertEqual(hashlib.sha256(system_png_bytes).hexdigest(), manifest["files"]["System/System.png"])

        # Check each fixture file on disk
        for rel_file, expected_hash in manifest["files"].items():
            full_path = os.path.join(fixture_dir, rel_file)
            self.assertTrue(os.path.exists(full_path), f"Missing RM2003 fixture file: {rel_file}")
            self.assertEqual(compute_sha256(full_path), expected_hash, f"Hash mismatch for fixture {rel_file}")

    def test_14_rm2003_easyrpg_rtp_positive_control(self):
        """Verify real EasyRPG Player resolves Hero1 from RM2003 target pack with zero missing asset warnings."""
        player_bin = shutil.which("easyrpg-player")
        require_runtime = os.environ.get("SUPERRTP_REQUIRE_RUNTIME") == "1"

        if not player_bin:
            if require_runtime:
                self.fail("easyrpg-player is required by SUPERRTP_REQUIRE_RUNTIME=1 but was not found on PATH")
            self.skipTest("easyrpg-player not found on PATH")

        fixture_dir = os.path.join(REPO_ROOT, "tests", "fixtures", "rm2003_min")
        rtp_dir = os.path.join(REPO_ROOT, "generated", "rm2003")

        if not os.path.exists(os.path.join(rtp_dir, "CharSet", "Actor1.png")):
            build_target("rm2003", output_dir=rtp_dir, clean=True)

        env = os.environ.copy()
        env["SDL_VIDEODRIVER"] = "dummy"
        env["SDL_AUDIODRIVER"] = "dummy"

        cmd = [
            player_bin,
            "--project-path", fixture_dir,
            "--rtp-path", rtp_dir,
            "--engine", "rpg2k3",
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

        # Hero1 resolved from RM2003 RTP
        self.assertNotIn("Image not found: CharSet/Hero1", output)
        # Bundled clean-room fixture assets resolved
        self.assertNotIn("Image not found: ChipSet", output)
        self.assertNotIn("Image not found: System", output)

    def test_15_rm2003_easyrpg_negative_control(self):
        """Verify real EasyRPG Player fails cleanly on Hero1 in RM2003 fixture when RTP is disabled."""
        player_bin = shutil.which("easyrpg-player")
        require_runtime = os.environ.get("SUPERRTP_REQUIRE_RUNTIME") == "1"

        if not player_bin:
            if require_runtime:
                self.fail("easyrpg-player is required by SUPERRTP_REQUIRE_RUNTIME=1 but was not found on PATH")
            self.skipTest("easyrpg-player not found on PATH")

        fixture_dir = os.path.join(REPO_ROOT, "tests", "fixtures", "rm2003_min")

        env = os.environ.copy()
        env["SDL_VIDEODRIVER"] = "dummy"
        env["SDL_AUDIODRIVER"] = "dummy"

        cmd = [
            player_bin,
            "--project-path", fixture_dir,
            "--no-rtp",
            "--engine", "rpg2k3",
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
        self.assertIn("Image not found: CharSet/Hero1", output)
        # Clean isolation: ChipSet and System still resolve
        self.assertNotIn("Image not found: ChipSet", output)
        self.assertNotIn("Image not found: System", output)

    def test_16_rm2003_directional_runtime_evidence_chain(self):
        """Verify RM2003 runtime evidence chain, hashes, and directional arrow assertions."""
        if os.environ.get("SUPERRTP_RUN_REPLAY") == "1":
            run_replay_and_record("rm2003")

        self.assertTrue(verify_evidence_chain("rm2003"), "RM2003 runtime verification evidence chain validation failed")

        artifact_dir = os.path.join(REPO_ROOT, "artifacts", "runtime", "rm2003", "charset")

        down_res = verify_directional_screenshot(os.path.join(artifact_dir, "rm2003_charset_down.png"), "down", target="rm2003")
        self.assertEqual(down_res["status"], "VERIFIED")
        self.assertGreater(down_res["shape_metrics"]["top_w"], down_res["shape_metrics"]["bot_w"])

        up_res = verify_directional_screenshot(os.path.join(artifact_dir, "rm2003_charset_up.png"), "up", target="rm2003")
        self.assertEqual(up_res["status"], "VERIFIED")
        self.assertLess(up_res["shape_metrics"]["top_w"], up_res["shape_metrics"]["bot_w"])

        left_res = verify_directional_screenshot(os.path.join(artifact_dir, "rm2003_charset_left.png"), "left", target="rm2003")
        self.assertEqual(left_res["status"], "VERIFIED")
        self.assertLess(left_res["shape_metrics"]["left_h"], left_res["shape_metrics"]["right_h"])

        right_res = verify_directional_screenshot(os.path.join(artifact_dir, "rm2003_charset_right.png"), "right", target="rm2003")
        self.assertEqual(right_res["status"], "VERIFIED")
        self.assertGreater(right_res["shape_metrics"]["left_h"], right_res["shape_metrics"]["right_h"])

        # Adversarial check: inverted direction expectation must fail
        with self.assertRaises(ValueError):
            verify_directional_screenshot(os.path.join(artifact_dir, "rm2003_charset_up.png"), "down", target="rm2003")

if __name__ == "__main__":
    unittest.main(verbosity=2)
