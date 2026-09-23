"""
Deterministic tests for the build pipeline: PNG codec, schemas, canonical assets and
provenance, pixel transforms, the target builder and the target validator.

No engine runtimes are needed. Run: python3 -m unittest tests/test_foundation.py
"""

import json
import os
import shutil
import struct
import tempfile
import unittest
import zlib

from support import REPO_ROOT, canonical_cell, canonical_walking_rgba, crop, read_bytes

import generate_calibration_charset
import generate_calibration_chipset
import transforms
from build_target import build_target
from png_utils import PngFormatError, create_indexed_png, create_rgba_png, read_png
from registry import check_provenance_record, find_provenance, list_targets, load_schema, load_slot_mapping
from repo import sha256_bytes, sha256_file
from schema_validator import SchemaValidationError, validate_schema
from validate_target import validate_png_wolf_character, validate_target

TARGETS = ("rm2000", "rm2003", "rmxp", "rmvx", "rmvxace", "wolf")


class TestPngCodec(unittest.TestCase):
    def test_rgba_round_trip_keeps_partial_alpha(self):
        pixels = bytes([10, 20, 30, 0, 40, 50, 60, 128, 70, 80, 90, 255, 1, 2, 3, 4])
        png = create_rgba_png(2, 2, pixels)
        self.assertEqual(read_png(png).pixels, pixels)
        self.assertEqual(png, create_rgba_png(2, 2, pixels), "encoder must be deterministic")

    def test_indexed_png_expands_palette_and_index0_transparency(self):
        png = create_indexed_png(2, 1, [(0, 0, 0), (200, 100, 50)], bytes([0, 1]))
        self.assertEqual(read_png(png).rgba_bytes(), bytes([0, 0, 0, 0, 200, 100, 50, 255]))

    def test_decoder_rejects_corruption_and_unsupported_formats(self):
        png = bytearray(create_rgba_png(2, 2, bytes(16)))
        png[-10] ^= 0xFF  # damage the IDAT CRC
        with self.assertRaises(PngFormatError):
            read_png(bytes(png))
        for bit_depth, interlace in ((16, 0), (8, 1)):
            ihdr = struct.pack(">IIBBBBB", 2, 2, bit_depth, 6, 0, 0, interlace)
            chunk = struct.pack(">I", 13) + b"IHDR" + ihdr + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr) & 0xFFFFFFFF)
            with self.assertRaises(PngFormatError):
                read_png(b"\x89PNG\r\n\x1a\n" + chunk)


class TestRegistry(unittest.TestCase):
    def test_all_registry_records_match_their_schemas(self):
        schemas = {name: load_schema(name) for name in ("slot_mapping", "asset", "provenance")}
        for target in list_targets():
            validate_schema(load_slot_mapping(target), schemas["slot_mapping"], target)
        for folder, schema in (("assets", "asset"), ("provenance", "provenance")):
            directory = os.path.join(REPO_ROOT, "registry", folder)
            for name in sorted(n for n in os.listdir(directory) if n.endswith(".json")):
                with open(os.path.join(directory, name)) as f:
                    validate_schema(json.load(f), schemas[schema], name)

    def test_slot_entries_are_schema_checked(self):
        # Regression: subschema-valued additionalProperties used to be ignored.
        mapping = load_slot_mapping("rm2000")
        mapping["slots"]["CharSet/Actor1.png"] = {"bogus": 1}
        with self.assertRaises(SchemaValidationError):
            validate_schema(mapping, load_schema("slot_mapping"))
        with self.assertRaises(SchemaValidationError):
            validate_schema({}, {"type": "object", "patternProperties": {}})

    def test_registry_aliases_match_easyrpg_rtp_tables(self):
        # docs/engine-facts.md: EasyRPG src/rtp_table.cpp (0.8.1.1) rows for these slots.
        expected = {
            ("rm2000", "CharSet/Actor1.png"): {"主人公1", "actor1", "chara1"},
            ("rm2003", "CharSet/Actor1.png"): {"主人公1", "actor1", "hero1", "chara1", "protagonist1", "주인공1", "主角1"},
            ("rm2000", "ChipSet/World.png"): {"基本", "world", "basis"},
            ("rm2003", "ChipSet/World.png"): {"基本", "world", "main", "basic", "기본"},
        }
        for (target, slot), names in expected.items():
            mapping = load_slot_mapping(target)["slots"][slot]
            stems = {os.path.splitext(os.path.basename(p))[0].lower() for p in mapping["upstream_aliases"] + [slot]}
            self.assertEqual(stems, {n.lower() for n in names}, f"{target} {slot}")
        # Engine-specific boundaries: 2003-only names must not leak into the 2000 pack and vice versa.
        rm2000 = {a.lower() for s in load_slot_mapping("rm2000")["slots"].values() for a in s["aliases"]}
        self.assertFalse({"charset/hero1.png", "chipset/main.png", "chipset/basic.png"} & rm2000)
        rm2003 = {a.lower() for s in load_slot_mapping("rm2003")["slots"].values() for a in s["aliases"]}
        self.assertNotIn("chipset/basis.png", rm2003)


class TestCanonicalAssets(unittest.TestCase):
    def test_generators_reproduce_committed_sources(self):
        rgba, png = generate_calibration_charset.generate_calibration_charset()
        self.assertEqual(rgba, canonical_walking_rgba())
        self.assertEqual(png, read_bytes("registry", "assets", "test_calibration_walking_character_master.png"))
        chip_rgba, chip_png = generate_calibration_chipset.generate_chipset()
        self.assertEqual(chip_rgba, read_bytes("registry", "assets", "test_calibration_map_chipset.rgba"))
        self.assertEqual(chip_png, read_bytes("registry", "assets", "test_calibration_map_chipset.master.png"))

    def test_provenance_rules(self):
        _, record = find_provenance("test.calibration.walking-character")
        digest = sha256_bytes(canonical_walking_rgba())
        self.assertEqual(check_provenance_record(record, digest)["license"], "CC0-1.0")
        bad_cases = {
            "hash": (dict(record), "0" * 64),
            "proprietary": (dict(record, clean_room_attestation=dict(record["clean_room_attestation"], proprietary_rtp_derived=True)), digest),
            "license": (dict(record, license="free for games"), digest),
            "external without evidence": (dict(record, source_type="externally_licensed"), digest),
        }
        for name, (prov, sha) in bad_cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                check_provenance_record(prov, sha)


class TestTransforms(unittest.TestCase):
    """Target sheets are compared cell by cell against crops located from the documented geometry."""

    @classmethod
    def setUpClass(cls):
        cls.src = canonical_walking_rgba()

    def _assert_layout(self, png, layout, source_chars):
        image = read_png(png)
        self.assertEqual((image.width, image.height), layout.size())
        for slot, char_idx in enumerate(source_chars):
            bx = (slot % layout.characters_across) * len(layout.columns) * 24
            by = (slot // layout.characters_across) * len(layout.rows) * 32
            for r, direction in enumerate(layout.rows):
                for c, phase in enumerate(layout.columns):
                    self.assertEqual(crop(image.pixels, image.width, bx + c * 24, by + r * 32),
                                     canonical_cell(self.src, char_idx, direction, phase),
                                     f"{layout.name} slot {slot} {direction}/{phase}")

    def test_character_targets_place_every_cell(self):
        self._assert_layout(transforms.transform_canonical_to_rmxp_character(self.src), transforms.RMXP_LAYOUT, [0])
        self._assert_layout(transforms.transform_canonical_to_wolf_character(self.src), transforms.WOLF_LAYOUT, [0])
        order = [3, 1, 4, 0, 7, 5, 2, 6]
        self._assert_layout(transforms.transform_canonical_to_rmvx_character(self.src, order), transforms.VX_FAMILY_LAYOUT, order)
        self.assertEqual(transforms.transform_canonical_to_rmvx_character(self.src),
                         transforms.transform_canonical_to_rmvxace_character(self.src))

    def test_rmxp_rests_on_idle_and_replays_the_2k_walk_cycle(self):
        # RGSS1 rests on column 0 and plays 0,1,2,3; EasyRPG rests on the middle frame and
        # plays middle, right, middle, left (docs/engine-facts.md).
        self.assertEqual(transforms.RMXP_LAYOUT.columns[0], "IDLE")
        self.assertEqual(transforms.RMXP_LAYOUT.columns, ("IDLE", "STEP_RIGHT", "IDLE", "STEP_LEFT"))

    def test_indexed_conversion_is_lossless_and_rejects_unrepresentable_input(self):
        rgba = read_png(transforms.transform_rgba_to_indexed_png(self.src)).rgba_bytes()
        for i in range(0, len(rgba), 4):
            if self.src[i + 3] == 0:
                self.assertEqual(rgba[i + 3], 0)
            else:
                self.assertEqual(rgba[i:i + 4], self.src[i:i + 4])
        with self.assertRaisesRegex(ValueError, "partial alpha"):
            transforms.transform_rgba_to_indexed_png(bytes([1, 2, 3, 128]) * 4, 2, 2)
        many = b"".join(bytes([i % 256, i // 256, 0, 255]) for i in range(300))
        with self.assertRaisesRegex(ValueError, "256-color"):
            transforms.transform_rgba_to_indexed_png(many, 300, 1)

    def test_packers_reject_malformed_input(self):
        chars = [transforms.extract_walking_frames(self.src, i) for i in range(8)]
        with self.assertRaises(ValueError):
            transforms.pack_rmvx_character_sheet(chars[:7])
        broken = [dict(chars[0], DOWN={"IDLE": chars[0]["DOWN"]["IDLE"]})] + chars[1:]
        with self.assertRaises(KeyError):
            transforms.pack_rmvx_character_sheet(broken)
        with self.assertRaises(ValueError):
            transforms.extract_walking_frames(self.src, 8)


class TestBuildAndValidate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="superrtp_test_")
        self.addCleanup(shutil.rmtree, self.tmp)

    def _build(self, target):
        out = os.path.join(self.tmp, target)
        build_target(target, output_dir=out, clean=True)
        return out

    def test_builds_are_reproducible_and_valid(self):
        for target in TARGETS:
            with self.subTest(target):
                out = self._build(target)
                committed = os.path.join(REPO_ROOT, "generated", target, "manifest.json")
                if os.path.exists(committed):
                    self.assertEqual(sha256_file(os.path.join(out, "manifest.json")), sha256_file(committed))
                self.assertEqual(validate_target(target, target_dir=out), 0)

    def _expect_rejected(self, target, mutate):
        out = self._build(target)
        mutate(out)
        self.assertEqual(validate_target(target, target_dir=out), 1)

    def test_validator_rejects_tampered_packs(self):
        def edit_manifest(change):
            def apply(out):
                path = os.path.join(out, "manifest.json")
                with open(path) as f:
                    manifest = json.load(f)
                change(manifest)
                with open(path, "w") as f:
                    json.dump(manifest, f)
            return apply

        def swap_rows(out):
            # DOWN and UP rows swapped, with the manifest hash updated so only pixel checks can catch it.
            path = os.path.join(out, "Graphics", "Characters", "Actor1.png")
            image = read_png(path)
            rows = bytearray(image.pixels)
            band = 288 * 32 * 4
            rows[:band], rows[3 * band:4 * band] = image.pixels[3 * band:4 * band], image.pixels[:band]
            with open(path, "wb") as f:
                f.write(create_rgba_png(288, 256, bytes(rows)))
            edit_manifest(lambda m: m["entries"][0].update(sha256=sha256_file(path)))(out)

        cases = {
            "missing alias file": ("rm2000", lambda out: os.remove(os.path.join(out, "CharSet", "chara1.png"))),
            "stray file": ("rm2000", lambda out: open(os.path.join(out, "CharSet", "extra.png"), "wb").close()),
            "dropped manifest entry": ("rm2003", edit_manifest(lambda m: m["entries"].pop())),
            "wrong transform policy": ("rmvx", edit_manifest(lambda m: m["entries"][0].update(transform_policy="x"))),
            "wrong asset id": ("wolf", edit_manifest(lambda m: m["entries"][0].update(asset_id="test.calibration.map-chipset"))),
            "row permutation": ("rmvxace", swap_rows),
            "not a png": ("wolf", lambda out: open(os.path.join(out, "Data", "CharaChip", "SuperRTP_Calibration.png"), "wb").write(b"junk")),
        }
        for name, (target, mutate) in cases.items():
            with self.subTest(name):
                self._expect_rejected(target, mutate)

    def test_png_spec_messages(self):
        with self.assertRaisesRegex(ValueError, "special filename mode"):
            validate_png_wolf_character(os.path.join(self.tmp, "HeroT.png"))
        path = os.path.join(self.tmp, "SuperRTP_Calibration.png")
        with open(path, "wb") as f:
            f.write(create_rgba_png(72, 120, bytes(72 * 120 * 4)))
        with self.assertRaisesRegex(ValueError, "Invalid WOLF Character dimensions"):
            validate_png_wolf_character(path)

    def test_clean_refuses_foreign_directories(self):
        with open(os.path.join(self.tmp, "keep.txt"), "w") as f:
            f.write("user data")
        with self.assertRaisesRegex(ValueError, "Refusing to clean"):
            build_target("wolf", output_dir=self.tmp, clean=True)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "keep.txt")))

    def test_cross_target_consistency(self):
        vx = read_png(os.path.join(self._build("rmvx"), "Graphics", "Characters", "Actor1.png"))
        wolf = read_png(os.path.join(self._build("wolf"), "Data", "CharaChip", "SuperRTP_Calibration.png"))
        self.assertEqual(wolf.pixels, crop(vx.pixels, 288, 0, 0, 72, 128), "WOLF CharaChip must equal the VX character-0 block")


if __name__ == "__main__":
    unittest.main()
