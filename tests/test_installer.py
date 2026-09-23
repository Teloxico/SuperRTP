"""
The pack installer (tools/release/install.py) on the OS it runs on. CI runs this module on
Linux, macOS and Windows; the engine side (EasyRPG finding an installed pack) is covered
by tools/verify_generated_packs.py.

Every run uses a synthetic pack and temporary HOME/XDG/LOCALAPPDATA folders. Tests that
write the Windows registry run only with SUPERRTP_TEST_REGISTRY=1 (set in CI), because
they write the real RPG Maker RTP registry values of the machine running them.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALLER = os.path.join(REPO_ROOT, "tools", "release", "install.py")
REGISTRY_TESTS = sys.platform == "win32" and os.environ.get("SUPERRTP_TEST_REGISTRY") == "1"
FILES = {"CharSet/Actor1.png": b"\x89PNG synthetic actor", "ChipSet/World.png": b"\x89PNG synthetic chipset"}


def make_pack(root: str, engine: str, files=FILES) -> str:
    pack_dir = os.path.join(root, f"SuperRTP-{engine}-test")
    for rel, data in files.items():
        path = os.path.join(pack_dir, "rtp", *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
    shutil.copyfile(INSTALLER, os.path.join(pack_dir, "install.py"))
    meta = {"pack": f"{engine}-test", "version": "0.0.0-test", "engine": engine, "engine_name": engine,
            "files": {rel: hashlib.sha256(data).hexdigest() for rel, data in files.items()}}
    with open(os.path.join(pack_dir, "superrtp-pack.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f)
    return pack_dir


class InstallerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="superrtp_installer_")
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.env = dict(os.environ, HOME=self.home, USERPROFILE=self.home, XDG_DATA_HOME=os.path.join(self.home, "xdg"),
                        LOCALAPPDATA=os.path.join(self.home, "localappdata"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_installer(self, pack_dir, *args, expect_ok=True):
        result = subprocess.run([sys.executable, os.path.join(pack_dir, "install.py"), *args], env=self.env,
                                capture_output=True, text=True)
        if expect_ok:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_default_install_goes_where_the_runtime_looks_and_uninstall_removes_it(self):
        if sys.platform == "win32" and not REGISTRY_TESTS:
            self.skipTest("the Windows default install registers HKCU RTP values (set SUPERRTP_TEST_REGISTRY=1)")
        pack = make_pack(self.tmp, "rm2000")
        self.run_installer(pack)
        if sys.platform == "win32":
            dest = os.path.join(self.env["LOCALAPPDATA"], "SuperRTP", "packs", "rm2000-test")
        else:   # EasyRPG Player's XDG RTP folder, on Linux and macOS alike
            dest = os.path.join(self.env["XDG_DATA_HOME"], "rtp", "2000")
        for rel, data in FILES.items():
            with open(os.path.join(dest, *rel.split("/")), "rb") as f:
                self.assertEqual(f.read(), data)
        if sys.platform == "win32":
            self.assertEqual(read_registry("HKCU", r"Software\ASCII\RPG2000", "RuntimePackagePath"), dest)
        self.run_installer(pack, "--uninstall")
        self.assertFalse(os.path.exists(dest))
        if sys.platform == "win32":
            self.assertIsNone(read_registry("HKCU", r"Software\ASCII\RPG2000", "RuntimePackagePath"))

    def test_existing_files_are_neither_overwritten_nor_removed(self):
        pack = make_pack(self.tmp, "wolf")
        game = os.path.join(self.tmp, "game")
        os.makedirs(os.path.join(game, "CharSet"))
        own = os.path.join(game, "CharSet", "Actor1.png")
        with open(own, "wb") as f:
            f.write(b"the game's own file")
        output = self.run_installer(pack, "--game", game).stdout
        self.assertIn("Kept 1 existing files", output)
        with open(own, "rb") as f:
            self.assertEqual(f.read(), b"the game's own file")
        self.assertTrue(os.path.isfile(os.path.join(game, "ChipSet", "World.png")))
        self.run_installer(pack, "--uninstall")
        self.assertTrue(os.path.isfile(own))
        self.assertFalse(os.path.exists(os.path.join(game, "ChipSet")))

    def test_mkxp_json_rtp_list_is_extended_and_restored(self):
        pack = make_pack(self.tmp, "rmvxace")
        conf = os.path.join(self.tmp, "mkxp.json")
        with open(conf, "w", encoding="utf-8") as f:
            json.dump({"rgssVersion": 3, "RTP": ["/somewhere/else"]}, f)
        self.run_installer(pack, "--mkxp-json", conf)
        with open(conf, encoding="utf-8") as f:
            rtp = json.load(f)["RTP"]
        dest = os.path.join(self.env["LOCALAPPDATA"] if sys.platform == "win32" else
                            os.path.join(self.home, "Library", "Application Support") if sys.platform == "darwin" else
                            self.env["XDG_DATA_HOME"], "SuperRTP", "packs", "rmvxace-test")
        self.assertEqual(rtp, ["/somewhere/else", os.path.abspath(dest)])
        self.assertTrue(os.path.isfile(os.path.join(dest, "CharSet", "Actor1.png")))
        self.run_installer(pack, "--uninstall")
        with open(conf, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["RTP"], ["/somewhere/else"])

    def test_mkxp_json_with_comments_is_left_untouched(self):
        pack = make_pack(self.tmp, "rmxp")
        conf = os.path.join(self.tmp, "mkxp.json")
        text = '{\n  // user comment\n  "RTP": []\n}\n'
        with open(conf, "w", encoding="utf-8") as f:
            f.write(text)
        result = self.run_installer(pack, "--mkxp-json", conf, expect_ok=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not plain JSON", result.stderr)
        with open(conf, encoding="utf-8") as f:
            self.assertEqual(f.read(), text)

    def test_corrupted_pack_is_refused(self):
        pack = make_pack(self.tmp, "rm2003")
        with open(os.path.join(pack, "rtp", "CharSet", "Actor1.png"), "ab") as f:
            f.write(b"tampered")
        result = self.run_installer(pack, "--dest", os.path.join(self.tmp, "out"), expect_ok=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("corrupted", result.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "out")))

    @unittest.skipUnless(REGISTRY_TESTS, "writes HKLM RTP values (Windows with SUPERRTP_TEST_REGISTRY=1)")
    def test_machine_registration_for_the_rgss_runtime(self):
        pack = make_pack(self.tmp, "rmvxace")
        dest = os.path.join(self.tmp, "installed")
        self.run_installer(pack, "--dest", dest, "--register", "machine")
        self.assertEqual(read_registry("HKLM", r"Software\Enterbrain\RGSS3\RTP", "RPGVXAce"), os.path.abspath(dest))
        other = make_pack(os.path.join(self.tmp, "other"), "rmvxace")
        output = self.run_installer(other, "--dest", os.path.join(self.tmp, "second"), "--register", "machine").stdout
        self.assertIn("left unchanged", output)
        self.run_installer(pack, "--uninstall")
        self.assertIsNone(read_registry("HKLM", r"Software\Enterbrain\RGSS3\RTP", "RPGVXAce"))


def read_registry(hive, key, name):
    import winreg
    root = {"HKCU": winreg.HKEY_CURRENT_USER, "HKLM": winreg.HKEY_LOCAL_MACHINE}[hive]
    try:
        with winreg.OpenKey(root, key, 0, winreg.KEY_READ | winreg.KEY_WOW64_32KEY) as handle:
            return winreg.QueryValueEx(handle, name)[0]
    except FileNotFoundError:
        return None


if __name__ == "__main__":
    unittest.main()
