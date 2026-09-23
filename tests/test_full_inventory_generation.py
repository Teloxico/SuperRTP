"""Coverage and determinism checks for the complete clean-room asset pipeline."""

import hashlib
import os
import re
import sys
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if TESTS_DIR not in sys.path:
    sys.path.insert(0, TESTS_DIR)

from support import REPO_ROOT

from asset_generation import flux_jobs
from asset_generation.generate_full_inventory import build_plan, load_spec, verify
from asset_generation.procedural_audio import audio_policy, render_audio
from asset_generation.procedural_visuals import encode_visual, render_visual, visual_policy


class TestFullInventoryGeneration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = load_spec()
        cls.plan = build_plan(cls.spec)

    def test_plan_covers_every_base_and_official_localized_path(self):
        self.assertEqual(len(self.plan), 5672)
        counts = {}
        for entry in self.plan:
            counts[entry["pack"]] = counts.get(entry["pack"], 0) + 1
        self.assertEqual(counts, {
            "rm2000-en": 466,
            "rm2000-ja": 465,
            "rm2003-en": 676,
            "rm2003-ja": 675,
            "rm2003-zh-tw": 676,
            "rmxp": 882,
            "rmvx": 439,
            "rmvxace": 748,
            "wolf": 645,
        })
        self.assertEqual(sum(entry["media"] == "visual" for entry in self.plan), 2934)
        self.assertEqual(sum(entry["media"] == "audio" for entry in self.plan), 2738)

    def test_clean_room_and_model_license_gates_are_explicit(self):
        attestation = self.spec["clean_room_attestation"]
        self.assertFalse(attestation["proprietary_creative_inputs_used"])
        self.assertFalse(attestation["upstream_pixels_or_audio_used"])
        self.assertEqual(self.spec["visual_generation"]["model_license"], "Apache-2.0")
        blocked = self.spec["evaluated_but_blocked_visual_backends"]
        self.assertEqual(blocked[0]["status"], "blocked-for-production")
        self.assertIn("Non-Commercial", blocked[0]["license"])

    def test_flux_jobs_cover_every_generated_family_with_authored_briefs(self):
        jobs = flux_jobs.plan_jobs(self.plan)
        self.assertEqual(len({job.job_id for job in jobs}), len(jobs))
        self.assertEqual([job.job_id for job in jobs if job.brief != "authored"], [])
        forbidden = re.compile(r"rpg ?maker|wolf rpg|rtp|easyrpg|enterbrain|kadokawa|degica|square enix|final fantasy",
                               re.IGNORECASE)
        self.assertEqual([job.job_id for job in jobs if forbidden.search(job.prompt)], [])
        planned = {job.family for job in jobs}
        visual_families = {entry["family"] for entry in self.plan if entry["media"] == "visual"}
        self.assertEqual(visual_families - planned, set(self.spec["visual_generation"]["procedural_families"]))
        for job in jobs:
            keyed = job.family in ("creature", "battle-character", "charset", "charset-xp", "charset-vx",
                                   "charset-vx-single", "faces", "faces-vx", "portrait", "icon")
            self.assertEqual(job.key_rgb is not None, keyed, job.job_id)

    def test_representative_media_are_byte_deterministic(self):
        for engine, path in (
            ("rm2000", "Backdrop/Forest1.png"),
            ("rm2003", "BattleCharSet/Warrior A.png"),
            ("rmxp", "Graphics/Battlebacks/001-Grassland01.jpg"),
            ("rmvx", "Graphics/Characters/Actor1.png"),
            ("rmvxace", "Graphics/Tilesets/Outside_A4.png"),
            ("wolf", "Data/MapChip/Auto_Water1_pipo.png"),
            ("rmvx", "Game.ico"),
        ):
            with self.subTest(engine=engine, path=path):
                policy = visual_policy(engine, path)
                first = encode_visual(engine, path, policy, render_visual(engine, path, policy))
                second = encode_visual(engine, path, policy, render_visual(engine, path, policy))
                self.assertEqual(hashlib.sha256(first).digest(), hashlib.sha256(second).digest())
        for path, creative_id in (
            ("Music/Battle1.mid", "audio.bgm.battle1"),
            ("Sound/Attack1.wav", "audio.se.attack1"),
            ("Audio/BGS/Rain.ogg", "audio.bgs.rain"),
        ):
            with self.subTest(path=path):
                policy = audio_policy(path)
                self.assertEqual(render_audio(path, creative_id, policy), render_audio(path, creative_id, policy))

    def test_generated_collection_is_hash_bound(self):
        manifest = os.path.join(REPO_ROOT, self.spec["output_root"], "manifest.json")
        if not os.path.isfile(manifest):
            self.skipTest("Full collection has not been generated yet")
        self.assertTrue(verify(self.spec, self.plan))


if __name__ == "__main__":
    unittest.main()
