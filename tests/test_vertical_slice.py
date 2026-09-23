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
from generate_calibration_chipset import generate_chipset as generate_calibration_chipset, WIDTH as CHIPSET_WIDTH, HEIGHT as CHIPSET_HEIGHT
from build_target import build_target
from repo import sha256_file as compute_sha256
from png_utils import create_indexed_png as create_png
from validate_target import validate_png_charset, validate_png_chipset, validate_target
from registry import verify_provenance
from schema_validator import validate_schema, SchemaValidationError
from generate_fixture_graphics import generate_minimal_chipset, generate_minimal_system, generate_minimal_charset
from verify_runtime import verify_evidence_chain, run_replay_and_record, verify_directional_screenshot
from verify_chipset_runtime import verify_evidence_chain as verify_chipset_evidence_chain, verify_chipset_screenshot

def compile_and_run_fixture_generator(target, output_dir, fixture_type="charset"):
    """
    Compiles tools/generate_fixture.cpp against pinned liblcf 0.8.1 and generates
    the minimal game fixture into output_dir.
    """
    os.makedirs(output_dir, exist_ok=True)
    cxx = shutil.which("g++") or shutil.which("clang++")
    require_runtime = os.environ.get("SUPERRTP_REQUIRE_RUNTIME") == "1"

    if not cxx:
        if require_runtime:
            raise RuntimeError("C++ compiler (g++ or clang++) required by SUPERRTP_REQUIRE_RUNTIME=1 but not found")
        raise unittest.SkipTest("C++ compiler not found on PATH")

    env = os.environ.copy()
    brew_pc = "/home/linuxbrew/.linuxbrew/opt/liblcf/lib/pkgconfig"
    if os.path.exists(brew_pc):
        curr_pc = env.get("PKG_CONFIG_PATH", "")
        env["PKG_CONFIG_PATH"] = f"{brew_pc}:{curr_pc}" if curr_pc else brew_pc

    try:
        modver_res = subprocess.run(["pkg-config", "--modversion", "liblcf"], env=env, capture_output=True, text=True, check=True)
        modver = modver_res.stdout.strip()
    except Exception as e:
        if require_runtime:
            raise RuntimeError(f"liblcf required by SUPERRTP_REQUIRE_RUNTIME=1 but pkg-config failed: {e}")
        raise unittest.SkipTest(f"liblcf not found via pkg-config: {e}")

    import re
    # Strictly require exact semantic version 0.8.1 (or package revisions like 0.8.1_1), rejecting 0.8.10 or 0.8.2
    if not re.match(r"^0\.8\.1(_\d+)?(-.*)?$", modver):
        raise ValueError(f"liblcf version pin violation: expected 0.8.1 (or packaging revision), got {modver}")

    cflags_res = subprocess.run(["pkg-config", "--cflags", "liblcf"], env=env, capture_output=True, text=True, check=True)
    libs_res = subprocess.run(["pkg-config", "--libs", "liblcf"], env=env, capture_output=True, text=True, check=True)
    cflags = cflags_res.stdout.split()
    libs = libs_res.stdout.split()

    brew_lib = "/home/linuxbrew/.linuxbrew/opt/liblcf/lib"
    rpath_flags = [f"-Wl,-rpath,{brew_lib}"] if os.path.exists(brew_lib) else []

    with tempfile.TemporaryDirectory(prefix="superrtp_genfix_bin_") as bin_dir:
        bin_path = os.path.join(bin_dir, "generate_fixture")
        src_cpp = os.path.join(REPO_ROOT, "tools", "generate_fixture.cpp")
        compile_cmd = [cxx, "-O2", "-std=c++17", src_cpp] + cflags + libs + rpath_flags + ["-o", bin_path]
        subprocess.run(compile_cmd, env=env, capture_output=True, text=True, check=True)

        run_cmd = [bin_path, output_dir, target, fixture_type]
        subprocess.run(run_cmd, env=env, capture_output=True, text=True, check=True)

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
        prov = verify_provenance("test.calibration.walking-character", sha256)

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

        # 8. Slot mapping schemas and alias taxonomy validation
        slots_schema_path = os.path.join(REPO_ROOT, "schemas", "slot_mapping.schema.json")
        with open(slots_schema_path, "r", encoding="utf-8") as ssf:
            slots_schema = json.load(ssf)
        for t in ("rm2000", "rm2003"):
            slot_file = os.path.join(REPO_ROOT, "registry", "slots", f"{t}.json")
            with open(slot_file, "r", encoding="utf-8") as sf:
                slot_data = json.load(sf)
            validate_schema(slot_data, slots_schema)

    def test_07_clean_room_fixture_manifest_integrity(self):
        """Verify clean-room test fixture binaries, dynamic C++ regeneration, and programmatic graphics match manifest."""
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

        # Dynamically compile and execute C++ generator into temporary directory and verify byte-for-byte identity
        with tempfile.TemporaryDirectory(prefix="superrtp_fixture_check_2k_") as gen_tmp:
            compile_and_run_fixture_generator("rm2000", gen_tmp)
            binary_files = ["Map0001.lmu", "RPG_RT.ini", "RPG_RT.ldb", "RPG_RT.lmt"]
            for bf in binary_files:
                gen_file = os.path.join(gen_tmp, bf)
                committed_file = os.path.join(fixture_dir, bf)
                self.assertTrue(os.path.exists(gen_file), f"Generator failed to produce {bf}")
                self.assertEqual(
                    compute_sha256(gen_file),
                    compute_sha256(committed_file),
                    f"Dynamic generator output diverged from committed {bf} in rm2000"
                )
                self.assertEqual(
                    compute_sha256(gen_file),
                    manifest["files"][bf],
                    f"Dynamic generator output diverged from manifest hash for {bf} in rm2000"
                )

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
        """Verify RM2003 builds deterministically across runs, shares identical Actor1.png with RM2000, and includes Hero1 alias."""
        temp_dir_2k3_a = tempfile.mkdtemp(prefix="superrtp_build2k3_a_")
        temp_dir_2k3_b = tempfile.mkdtemp(prefix="superrtp_build2k3_b_")
        temp_dir_2k = tempfile.mkdtemp(prefix="superrtp_build2k_")
        try:
            # 1. Build RM2003 twice with identical static timestamp and verify full byte-for-byte tree identity
            build_target("rm2003", output_dir=temp_dir_2k3_a, clean=True, timestamp=0)
            build_target("rm2003", output_dir=temp_dir_2k3_b, clean=True, timestamp=0)

            for root, _, files in os.walk(temp_dir_2k3_a):
                rel_dir = os.path.relpath(root, temp_dir_2k3_a)
                for f in files:
                    pa = os.path.join(root, f)
                    pb = os.path.join(temp_dir_2k3_b, rel_dir, f)
                    self.assertTrue(os.path.exists(pb), f"Missing file in duplicate RM2003 build: {f}")
                    self.assertEqual(compute_sha256(pa), compute_sha256(pb), f"RM2003 build divergence in {f}")

            # 2. Build RM2000 and verify primary Actor1.png is byte-for-byte identical across RM2000 and RM2003
            build_target("rm2000", output_dir=temp_dir_2k, clean=True, timestamp=0)
            p2k_actor1 = os.path.join(temp_dir_2k, "CharSet", "Actor1.png")
            p2k3_actor1 = os.path.join(temp_dir_2k3_a, "CharSet", "Actor1.png")
            self.assertEqual(compute_sha256(p2k_actor1), compute_sha256(p2k3_actor1),
                             "Actor1.png must be byte-identical between RM2000 and RM2003 builds")

            # 3. Check RM2003-specific aliases: Hero1 must exist in RM2003 but not in RM2000
            self.assertTrue(os.path.exists(os.path.join(temp_dir_2k3_a, "CharSet", "Hero1.png")),
                            "RM2003 must contain Hero1.png")
            self.assertFalse(os.path.exists(os.path.join(temp_dir_2k, "CharSet", "Hero1.png")),
                             "RM2000 must NOT contain Hero1.png")

            # 4. Check RM2003 manifest entries
            manifest_path = os.path.join(temp_dir_2k3_a, "manifest.json")
            with open(manifest_path, "r") as f:
                manifest = json.load(f)
            self.assertEqual(manifest["target"], "rm2003")
            entries = {e["slot"]: e for e in manifest["entries"]}
            self.assertIn("CharSet/Hero1.png", entries)
            self.assertFalse(entries["CharSet/Hero1.png"]["is_primary"])
            self.assertEqual(entries["CharSet/Hero1.png"]["primary_slot"], "CharSet/Actor1.png")

            # 5. Target validator passes on RM2003
            exit_code = validate_target("rm2003", target_dir=temp_dir_2k3_a)
            self.assertEqual(exit_code, 0)
        finally:
            shutil.rmtree(temp_dir_2k3_a, ignore_errors=True)
            shutil.rmtree(temp_dir_2k3_b, ignore_errors=True)
            shutil.rmtree(temp_dir_2k, ignore_errors=True)

    def test_13_rm2003_clean_room_fixture_integrity(self):
        """Verify RM2003 clean-room test fixture binaries, dynamic C++ regeneration, and programmatic graphics match manifest."""
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

        # Dynamically compile and execute C++ generator into temporary directory and verify byte-for-byte identity
        with tempfile.TemporaryDirectory(prefix="superrtp_fixture_check_2k3_") as gen_tmp:
            compile_and_run_fixture_generator("rm2003", gen_tmp)
            binary_files = ["Map0001.lmu", "RPG_RT.ini", "RPG_RT.ldb", "RPG_RT.lmt"]
            for bf in binary_files:
                gen_file = os.path.join(gen_tmp, bf)
                committed_file = os.path.join(fixture_dir, bf)
                self.assertTrue(os.path.exists(gen_file), f"Generator failed to produce {bf}")
                self.assertEqual(
                    compute_sha256(gen_file),
                    compute_sha256(committed_file),
                    f"Dynamic generator output diverged from committed {bf} in rm2003"
                )
                self.assertEqual(
                    compute_sha256(gen_file),
                    manifest["files"][bf],
                    f"Dynamic generator output diverged from manifest hash for {bf} in rm2003"
                )

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

    def test_17_chipset_canonical_asset_and_slot_mappings(self):
        """Verify ChipSet canonical asset reproducibility, schemas, and engine-specific slot mappings."""
        raw1, png1 = generate_calibration_chipset()
        raw2, png2 = generate_calibration_chipset()
        self.assertEqual(raw1, raw2, "Raw RGBA ChipSet generator must be deterministic")
        self.assertEqual(png1, png2, "Master preview ChipSet generator must be deterministic")

        rgba_path = os.path.join(REPO_ROOT, "registry", "assets", "test_calibration_map_chipset.rgba")
        self.assertTrue(os.path.exists(rgba_path), f"Canonical ChipSet RGBA not found at {rgba_path}")
        self.assertEqual(compute_sha256(rgba_path), hashlib.sha256(raw1).hexdigest())

        master_png_path = os.path.join(REPO_ROOT, "registry", "assets", "test_calibration_map_chipset.master.png")
        self.assertTrue(os.path.exists(master_png_path))
        self.assertEqual(compute_sha256(master_png_path), hashlib.sha256(png1).hexdigest())

        meta_path = os.path.join(REPO_ROOT, "registry", "assets", "test_calibration_map_chipset.json")
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        self.assertEqual(meta["sha256"], compute_sha256(rgba_path))
        self.assertEqual(meta["type"], "chipset")
        self.assertEqual(meta["dimensions"], {"width": 480, "height": 256})

        # Validate asset & provenance schemas
        asset_schema_path = os.path.join(REPO_ROOT, "schemas", "asset.schema.json")
        with open(asset_schema_path, "r", encoding="utf-8") as asf:
            asset_schema = json.load(asf)
        validate_schema(meta, asset_schema)

        prov = verify_provenance("test.calibration.map-chipset", compute_sha256(rgba_path))
        self.assertEqual(prov["source_type"], "project_synthetic")
        self.assertEqual(prov["license"], "CC0-1.0")

        # Slot mapping validations: RM2000 vs RM2003 taxonomy
        with open(os.path.join(REPO_ROOT, "registry", "slots", "rm2000.json"), "r", encoding="utf-8") as f2k:
            slots_2k = json.load(f2k)
        with open(os.path.join(REPO_ROOT, "registry", "slots", "rm2003.json"), "r", encoding="utf-8") as f2k3:
            slots_2k3 = json.load(f2k3)

        self.assertIn("ChipSet/World.png", slots_2k["slots"])
        self.assertIn("ChipSet/World.png", slots_2k3["slots"])

        cs_2k = slots_2k["slots"]["ChipSet/World.png"]
        cs_2k3 = slots_2k3["slots"]["ChipSet/World.png"]

        # RM2000 has Basis, but strictly NO Main or Basic
        self.assertIn("ChipSet/basis.png", cs_2k["upstream_aliases"])
        self.assertIn("ChipSet/Basis.png", cs_2k["emitted_case_variants"])
        self.assertNotIn("ChipSet/Main.png", cs_2k["emitted_case_variants"])
        self.assertNotIn("ChipSet/Basic.png", cs_2k["emitted_case_variants"])

        # RM2003 has Main and Basic, but strictly NO Basis
        self.assertIn("ChipSet/main.png", cs_2k3["upstream_aliases"])
        self.assertIn("ChipSet/basic.png", cs_2k3["upstream_aliases"])
        self.assertIn("ChipSet/Main.png", cs_2k3["emitted_case_variants"])
        self.assertIn("ChipSet/Basic.png", cs_2k3["emitted_case_variants"])
        self.assertNotIn("ChipSet/Basis.png", cs_2k3["emitted_case_variants"])

    def test_18_chipset_target_build_and_validation(self):
        """Verify ChipSet target building, cross-target byte determinism, and validator compliance."""
        temp_dir_2k = tempfile.mkdtemp(prefix="superrtp_test_build_cs2k_")
        temp_dir_2k3 = tempfile.mkdtemp(prefix="superrtp_test_build_cs2k3_")
        try:
            build_target("rm2000", output_dir=temp_dir_2k, clean=True)
            build_target("rm2003", output_dir=temp_dir_2k3, clean=True)

            world_2k = os.path.join(temp_dir_2k, "ChipSet", "World.png")
            world_2k3 = os.path.join(temp_dir_2k3, "ChipSet", "World.png")
            self.assertTrue(os.path.exists(world_2k))
            self.assertTrue(os.path.exists(world_2k3))

            # Cross-target byte determinism: identical canonical asset yields bit-for-bit identical World.png
            self.assertEqual(compute_sha256(world_2k), compute_sha256(world_2k3))

            # RM2000 has Basis.png, NO Main.png
            self.assertTrue(os.path.exists(os.path.join(temp_dir_2k, "ChipSet", "Basis.png")))
            self.assertFalse(os.path.exists(os.path.join(temp_dir_2k, "ChipSet", "Main.png")))

            # RM2003 has Main.png and Basic.png, NO Basis.png
            self.assertTrue(os.path.exists(os.path.join(temp_dir_2k3, "ChipSet", "Main.png")))
            self.assertTrue(os.path.exists(os.path.join(temp_dir_2k3, "ChipSet", "Basic.png")))
            self.assertFalse(os.path.exists(os.path.join(temp_dir_2k3, "ChipSet", "Basis.png")))

            # Structural validation of generated ChipSet PNG
            validate_png_chipset(world_2k)

            # Assert manifest entries contain semantic category
            with open(os.path.join(temp_dir_2k, "manifest.json"), "r", encoding="utf-8") as mf:
                m_2k = json.load(mf)
            for entry in m_2k["entries"]:
                self.assertIn("category", entry)
                self.assertIn(entry["category"], ["CharSet", "ChipSet"])

            # Full target validation passes
            self.assertEqual(validate_target("rm2000", target_dir=temp_dir_2k), 0)
            self.assertEqual(validate_target("rm2003", target_dir=temp_dir_2k3), 0)

            # Adversarial check: category mismatch between manifest and registry fails validation
            m_tampered = dict(m_2k)
            m_tampered["entries"] = [dict(e) for e in m_2k["entries"]]
            # Change ChipSet/World.png category to CharSet
            for e in m_tampered["entries"]:
                if e["slot"] == "ChipSet/World.png":
                    e["category"] = "CharSet"
            tamper_manifest_path = os.path.join(temp_dir_2k, "manifest.json")
            with open(tamper_manifest_path, "w", encoding="utf-8") as mf:
                json.dump(m_tampered, mf, indent=2)
            self.assertNotEqual(validate_target("rm2000", target_dir=temp_dir_2k), 0)

            # Restore valid manifest
            with open(tamper_manifest_path, "w", encoding="utf-8") as mf:
                json.dump(m_2k, mf, indent=2)
        finally:
            shutil.rmtree(temp_dir_2k, ignore_errors=True)
            shutil.rmtree(temp_dir_2k3, ignore_errors=True)

    def test_19_chipset_clean_room_fixtures_integrity(self):
        """Verify RM2000 and RM2003 clean-room ChipSet fixture manifests, dynamic LCF regeneration, and bundled graphics."""
        for target in ["rm2000", "rm2003"]:
            f_dir = os.path.join(REPO_ROOT, "tests", "fixtures", f"{target}_chipset_min")
            man_path = os.path.join(f_dir, "fixture_manifest.json")
            self.assertTrue(os.path.exists(man_path), f"Fixture manifest missing: {man_path}")
            with open(man_path, "r") as f:
                manifest = json.load(f)

            # Check generators
            gen_cpp_path = os.path.join(REPO_ROOT, manifest["generator_source"])
            self.assertEqual(compute_sha256(gen_cpp_path), manifest["generator_sha256"])
            gen_py_path = os.path.join(REPO_ROOT, manifest["graphics_generator_source"])
            self.assertEqual(compute_sha256(gen_py_path), manifest["graphics_generator_sha256"])

            # Dynamically compile and execute C++ generator into temporary directory and verify byte identity
            with tempfile.TemporaryDirectory(prefix=f"superrtp_fixcheck_{target}_cs_") as gen_tmp:
                compile_and_run_fixture_generator(target, gen_tmp, fixture_type="chipset")
                binary_files = ["Map0001.lmu", "RPG_RT.ini", "RPG_RT.ldb", "RPG_RT.lmt"]
                for bf in binary_files:
                    gen_file = os.path.join(gen_tmp, bf)
                    committed_file = os.path.join(f_dir, bf)
                    self.assertTrue(os.path.exists(gen_file))
                    self.assertEqual(compute_sha256(gen_file), compute_sha256(committed_file))
                    self.assertEqual(compute_sha256(gen_file), manifest["files"][bf])

            # Verify programmatic regeneration of System and CharSet
            system_bytes = generate_minimal_system()
            charset_bytes = generate_minimal_charset()
            self.assertEqual(hashlib.sha256(system_bytes).hexdigest(), manifest["files"]["System/System.png"])
            self.assertEqual(hashlib.sha256(charset_bytes).hexdigest(), manifest["files"]["CharSet/Actor1.png"])
            if target == "rm2003":
                self.assertEqual(hashlib.sha256(charset_bytes).hexdigest(), manifest["files"]["CharSet/Hero1.png"])

            # ZERO ChipSet in fixture directory
            self.assertFalse(os.path.exists(os.path.join(f_dir, "ChipSet")), f"Fixture must NOT contain ChipSet: {f_dir}")

    def test_20_rm2000_chipset_easyrpg_runtime_controls(self):
        """Verify real EasyRPG Player resolves Basis from RM2000 target pack, and isolates missing ChipSet/Basis without RTP."""
        player_bin = shutil.which("easyrpg-player")
        require_runtime = os.environ.get("SUPERRTP_REQUIRE_RUNTIME") == "1"
        if not player_bin:
            if require_runtime:
                self.fail("easyrpg-player is required by SUPERRTP_REQUIRE_RUNTIME=1 but was not found on PATH")
            self.skipTest("easyrpg-player not found on PATH")

        fixture_dir = os.path.join(REPO_ROOT, "tests", "fixtures", "rm2000_chipset_min")
        rtp_dir = os.path.join(REPO_ROOT, "generated", "rm2000")
        if not os.path.exists(os.path.join(rtp_dir, "ChipSet", "World.png")):
            build_target("rm2000", output_dir=rtp_dir, clean=False)

        env = os.environ.copy()
        env["SDL_VIDEODRIVER"] = "dummy"
        env["SDL_AUDIODRIVER"] = "dummy"

        # 1. Positive control
        cmd_pos = [
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
            res = subprocess.run(cmd_pos, env=env, capture_output=True, text=True, timeout=3.5)
            out_pos = res.stdout + res.stderr
        except subprocess.TimeoutExpired as e:
            out_pos = (e.stdout or b'').decode('utf-8', errors='replace') + (e.stderr or b'').decode('utf-8', errors='replace')

        self.assertIn("Adding", out_pos)
        self.assertIn("to RTP path", out_pos)
        self.assertNotIn("Image not found: ChipSet", out_pos)
        self.assertNotIn("Image not found: CharSet", out_pos)
        self.assertNotIn("Image not found: System", out_pos)

        # 2. Negative control
        cmd_neg = [
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
            res = subprocess.run(cmd_neg, env=env, capture_output=True, text=True, timeout=3.5)
            out_neg = res.stdout + res.stderr
        except subprocess.TimeoutExpired as e:
            out_neg = (e.stdout or b'').decode('utf-8', errors='replace') + (e.stderr or b'').decode('utf-8', errors='replace')

        self.assertIn("RTP support is disabled", out_neg)
        self.assertIn("Image not found: ChipSet/Basis", out_neg)
        self.assertNotIn("Image not found: CharSet", out_neg)
        self.assertNotIn("Image not found: System", out_neg)

    def test_21_rm2003_chipset_easyrpg_runtime_controls(self):
        """Verify real EasyRPG Player resolves Main from RM2003 target pack, and isolates missing ChipSet/Main without RTP."""
        player_bin = shutil.which("easyrpg-player")
        require_runtime = os.environ.get("SUPERRTP_REQUIRE_RUNTIME") == "1"
        if not player_bin:
            if require_runtime:
                self.fail("easyrpg-player is required by SUPERRTP_REQUIRE_RUNTIME=1 but was not found on PATH")
            self.skipTest("easyrpg-player not found on PATH")

        fixture_dir = os.path.join(REPO_ROOT, "tests", "fixtures", "rm2003_chipset_min")
        rtp_dir = os.path.join(REPO_ROOT, "generated", "rm2003")
        if not os.path.exists(os.path.join(rtp_dir, "ChipSet", "World.png")):
            build_target("rm2003", output_dir=rtp_dir, clean=False)

        env = os.environ.copy()
        env["SDL_VIDEODRIVER"] = "dummy"
        env["SDL_AUDIODRIVER"] = "dummy"

        # 1. Positive control
        cmd_pos = [
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
            res = subprocess.run(cmd_pos, env=env, capture_output=True, text=True, timeout=3.5)
            out_pos = res.stdout + res.stderr
        except subprocess.TimeoutExpired as e:
            out_pos = (e.stdout or b'').decode('utf-8', errors='replace') + (e.stderr or b'').decode('utf-8', errors='replace')

        self.assertIn("Adding", out_pos)
        self.assertIn("to RTP path", out_pos)
        self.assertNotIn("Image not found: ChipSet", out_pos)
        self.assertNotIn("Image not found: CharSet", out_pos)
        self.assertNotIn("Image not found: System", out_pos)

        # 2. Negative control
        cmd_neg = [
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
            res = subprocess.run(cmd_neg, env=env, capture_output=True, text=True, timeout=3.5)
            out_neg = res.stdout + res.stderr
        except subprocess.TimeoutExpired as e:
            out_neg = (e.stdout or b'').decode('utf-8', errors='replace') + (e.stderr or b'').decode('utf-8', errors='replace')

        self.assertIn("RTP support is disabled", out_neg)
        self.assertIn("Image not found: ChipSet/Main", out_neg)
        self.assertNotIn("Image not found: CharSet", out_neg)
        self.assertNotIn("Image not found: System", out_neg)

    def test_22_chipset_runtime_evidence_and_layer_transparency(self):
        """Verify durable ChipSet runtime verification evidence chain, hashes, and layer transparency composition."""
        for target in ["rm2000", "rm2003"]:
            self.assertTrue(verify_chipset_evidence_chain(target))

            artifact_dir = os.path.join(REPO_ROOT, "artifacts", "runtime", target, "chipset")
            pos_shot = os.path.join(artifact_dir, f"{target}_chipset_positive.png")
            res = verify_chipset_screenshot(pos_shot, mode="positive", target=target)
            self.assertEqual(res["status"], "VERIFIED")

            # Assert exact mechanical colors:
            # 1. Block E Bank 1 lower tile 5000: Yellow center, Cyan border, Blue bg
            self.assertEqual(res["tile_5000"]["center"], [255, 220, 30])
            self.assertEqual(res["tile_5000"]["border"], [0, 240, 255])
            self.assertEqual(res["tile_5000"]["bg"], [12, 48, 160])

            # 2. Block E Bank 2 lower tile 5096: Magenta center, Lime border, Green bg
            self.assertEqual(res["tile_5096"]["center"], [250, 40, 200])
            self.assertEqual(res["tile_5096"]["border"], [50, 255, 80])
            self.assertEqual(res["tile_5096"]["bg"], [15, 120, 45])

            # 3. Block F Bank 2 upper tile 10048: Orange center
            self.assertEqual(res["tile_10048"]["center"], [255, 130, 10])

            # 4. Upper/lower layer transparency composition: Tile 10000 over Tile 5000
            # Red cross at center
            self.assertEqual(res["tile_10000_over_5000"]["upper_center_cross"], [230, 30, 30])
            # Lower tile border visible through upper transparent corner
            self.assertEqual(res["tile_10000_over_5000"]["lower_border_through_transparency"], [0, 240, 255])
            # Lower tile bg visible through upper transparent interior
            self.assertEqual(res["tile_10000_over_5000"]["lower_bg_through_transparency"], [12, 48, 160])

            # Adversarial check: verify negative control fails if evaluated as positive
            neg_shot = os.path.join(artifact_dir, f"{target}_chipset_negative_control.png")
            with self.assertRaises(ValueError):
                verify_chipset_screenshot(neg_shot, mode="positive", target=target)

    def test_23_chipset_runtime_evidence_tamper_rejection(self):
        """Verify that ChipSet evidence verification strictly rejects tampering across all bound inputs."""
        src_art_dir = os.path.join(REPO_ROOT, "artifacts", "runtime", "rm2000", "chipset")
        src_target_dir = os.path.join(REPO_ROOT, "generated", "rm2000")
        src_fixture_dir = os.path.join(REPO_ROOT, "tests", "fixtures", "rm2000_chipset_min")
        src_canonical = os.path.join(REPO_ROOT, "registry", "assets", "test_calibration_map_chipset.rgba")

        if not os.path.exists(os.path.join(src_target_dir, "manifest.json")):
            build_target("rm2000", output_dir=src_target_dir, clean=False)

        def _setup_sandbox(tmp):
            tmp_art = os.path.join(tmp, "artifacts")
            tmp_tgt = os.path.join(tmp, "generated")
            tmp_fix = os.path.join(tmp, "fixture")
            tmp_can = os.path.join(tmp, "canonical.rgba")
            shutil.copytree(src_art_dir, tmp_art)
            shutil.copytree(src_target_dir, tmp_tgt)
            shutil.copytree(src_fixture_dir, tmp_fix)
            shutil.copyfile(src_canonical, tmp_can)
            ev_path = os.path.join(tmp_art, "verification_evidence.json")
            return {
                "evidence_path": ev_path,
                "artifacts_dir": tmp_art,
                "target_dir": tmp_tgt,
                "fixture_dir": tmp_fix,
                "canonical_rgba_path": tmp_can,
            }

        # Verify clean sandbox passes first
        with tempfile.TemporaryDirectory(prefix="superrtp_tamper_clean_") as tmp:
            paths = _setup_sandbox(tmp)
            self.assertTrue(
                verify_chipset_evidence_chain(
                    target="rm2000",
                    evidence_path=paths["evidence_path"],
                    artifacts_dir=paths["artifacts_dir"],
                    target_dir=paths["target_dir"],
                    fixture_dir=paths["fixture_dir"],
                    canonical_rgba_path=paths["canonical_rgba_path"],
                )
            )

        def _mutate_json(path, key, val):
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            d[key] = val
            with open(path, "w", encoding="utf-8") as f:
                json.dump(d, f, indent=2)

        def _mutate_json_sub(path, sub, key, val):
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            d[sub][key] = val
            with open(path, "w", encoding="utf-8") as f:
                json.dump(d, f, indent=2)

        def _write_file(path, content, is_bytes=False):
            mode = "wb" if is_bytes else "w"
            encoding = None if is_bytes else "utf-8"
            with open(path, mode, encoding=encoding) as f:
                f.write(content)

        tamper_cases = [
            ("canonical_source_content", lambda p: _write_file(p["canonical_rgba_path"], b"tampered_source", is_bytes=True)),
            ("canonical_source_sha256", lambda p: _mutate_json(p["evidence_path"], "canonical_source_sha256", "0" * 64)),
            ("target_world_file", lambda p: _write_file(os.path.join(p["target_dir"], "ChipSet", "World.png"), b"tampered_world", is_bytes=True)),
            ("target_world_sha256", lambda p: _mutate_json(p["evidence_path"], "target_world_sha256", "0" * 64)),
            ("target_manifest_file", lambda p: _write_file(os.path.join(p["target_dir"], "manifest.json"), "{}")),
            ("target_manifest_sha256", lambda p: _mutate_json(p["evidence_path"], "target_manifest_sha256", "0" * 64)),
            ("fixture_manifest_file", lambda p: _write_file(os.path.join(p["fixture_dir"], "fixture_manifest.json"), "{}")),
            ("fixture_manifest_sha256", lambda p: _mutate_json(p["evidence_path"], "fixture_manifest_sha256", "0" * 64)),
            ("positive_runtime_log_content", lambda p: _write_file(os.path.join(p["artifacts_dir"], "positive_runtime.log"), "tampered")),
            ("negative_runtime_log_content", lambda p: _write_file(os.path.join(p["artifacts_dir"], "negative_runtime.log"), "tampered")),
            ("negative_log_diagnostic_removed", lambda p: _write_file(os.path.join(p["artifacts_dir"], "negative_runtime.log"), "No error logged")),
            ("negative_control_diagnostic", lambda p: _mutate_json_sub(p["evidence_path"], "negative_control", "diagnostic", "Wrong Diagnostic")),
            ("negative_control_status", lambda p: _mutate_json_sub(p["evidence_path"], "negative_control", "status", "FAILED")),
            ("screenshot_file", lambda p: _write_file(os.path.join(p["artifacts_dir"], "rm2000_chipset_positive.png"), b"tampered_png", is_bytes=True)),
            ("screenshot_sha256", lambda p: _mutate_json_sub(p["evidence_path"], "screenshots", "rm2000_chipset_positive.png", "0" * 64)),
            ("engine_mode", lambda p: _mutate_json(p["evidence_path"], "engine_mode", "banana")),
            ("requested_chipset", lambda p: _mutate_json(p["evidence_path"], "requested_chipset", "NotARealThing")),
            ("easyrpg_version", lambda p: _mutate_json(p["evidence_path"], "easyrpg_version", "EasyRPG Player 9.9.9")),
        ]

        tested_count = 0
        for name, mutate_fn in tamper_cases:
            with tempfile.TemporaryDirectory(prefix=f"superrtp_tamper_{name}_") as tmp:
                p = _setup_sandbox(tmp)
                mutate_fn(p)
                with self.assertRaises((ValueError, FileNotFoundError), msg=f"Tamper case '{name}' was not rejected by verify_chipset_evidence_chain"):
                    verify_chipset_evidence_chain(
                        target="rm2000",
                        evidence_path=p["evidence_path"],
                        artifacts_dir=p["artifacts_dir"],
                        target_dir=p["target_dir"],
                        fixture_dir=p["fixture_dir"],
                        canonical_rgba_path=p["canonical_rgba_path"],
                    )
                tested_count += 1

        self.assertEqual(tested_count, len(tamper_cases))

if __name__ == "__main__":
    unittest.main(verbosity=2)
