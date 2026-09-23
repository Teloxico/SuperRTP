#!/usr/bin/env python3
"""
Packages the verified full-inventory packs (artifacts/generation/full-inventory/v2) into
one self-installing archive per pack, so every engine's pack can be downloaded and
installed on its own:

    dist/SuperRTP-<pack>-<version>.zip
      SuperRTP-<pack>/install.py            tools/release/install.py (Python 3.8+, any OS)
      SuperRTP-<pack>/superrtp-pack.json    pack id, engine, version, SHA-256 of every file
      SuperRTP-<pack>/README.txt            what the pack is and how to install it
      SuperRTP-<pack>/LICENSE.txt           CC0-1.0 (assets) and MIT (installer)
      SuperRTP-<pack>/rtp/...               the pack's files at their engine paths
    dist/SHA256SUMS

Archives are reproducible: sorted entries, fixed timestamps and permissions. The packs
must first pass generate_full_inventory.py --check, which this script runs.

    python3 tools/release/package_release.py [--pack rm2000-en ...] [--out dist]
"""

import argparse
import hashlib
import io
import json
import os
import sys
import zipfile

TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS_DIR)

from asset_generation import generate_full_inventory as inventory  # noqa: E402
from repo import REPO_ROOT, sha256_file  # noqa: E402

VERSION_FILE = os.path.join(REPO_ROOT, "VERSION")
INSTALLER = os.path.join(TOOLS_DIR, "release", "install.py")
ZIP_TIME = (1980, 1, 1, 0, 0, 0)
ENGINE_NAMES = {
    "rm2000": "RPG Maker 2000", "rm2003": "RPG Maker 2003", "rmxp": "RPG Maker XP",
    "rmvx": "RPG Maker VX", "rmvxace": "RPG Maker VX Ace", "wolf": "WOLF RPG Editor",
}
LOCALE_NAMES = {"en": "English file names", "ja": "Japanese file names", "zh-tw": "Traditional Chinese file names",
                "base": "file names of the base distribution"}

HOW_TO = {
    "rm2000": """EasyRPG Player on Linux or macOS
    python3 install.py
  installs to ~/.local/share/rtp/2000 (or $XDG_DATA_HOME/rtp/2000), which EasyRPG
  Player searches automatically.

Windows (EasyRPG Player or RPG_RT.exe)
    py install.py
  copies the pack to %LOCALAPPDATA%\\SuperRTP\\packs and registers it under
  HKCU\\Software\\ASCII\\RPG2000 (RuntimePackagePath), where EasyRPG Player looks.
  The original RTP installer registers under HKLM instead; to do the same, run
    py install.py --register machine
  from an administrator prompt. An RTP that is already registered is never replaced.

Windows games under Wine (Linux/macOS)
    python3 install.py --wine-prefix ~/.wine""",
    "rmxp": """mkxp-z (Windows, Linux, macOS)
    python3 install.py --mkxp-json /path/to/game/mkxp.json
  copies the pack to your user data folder and adds it to the "RTP" list of that
  mkxp.json.

Windows, the game's own Game.exe
    py install.py --register machine        (administrator prompt)
  registers the pack as the RTP named "{rtp_name}" under
  HKLM\\Software\\Enterbrain\\{rgss}\\RTP, the key the RGSS runtime reads. An RTP that
  is already registered is never replaced.

Windows games under Wine (Linux/macOS)
    python3 install.py --wine-prefix ~/.wine --register machine""",
    "wolf": """WOLF RPG Editor has no shared runtime package: every game carries its own Data
folder. To fill in files a game folder is missing:
    python3 install.py --game /path/to/game/Data""",
}
HOW_TO["rm2003"] = HOW_TO["rm2000"].replace("2000", "2003").replace(
    "HKCU\\Software\\ASCII\\RPG2003 (RuntimePackagePath)", "HKCU\\Software\\Enterbrain\\RPG2003 (RUNTIMEPACKAGEPATH)")
RGSS = {"rmxp": ("RGSS", "Standard"), "rmvx": ("RGSS2", "RPGVX"), "rmvxace": ("RGSS3", "RPGVXAce")}

README = """SuperRTP {pack} {version}
{engine_name} replacement runtime package ({locale})

SuperRTP packs fill the file names a game expects from the {engine_name} runtime
package (RTP) with independently created, openly licensed images. They contain no
proprietary RTP content. A game that uses the original RTP artwork will run, but it
will look different: these are replacements, not copies.

This pack: {file_count} image files. Music and sound effects are not included yet.

INSTALLING (needs Python 3.8 or newer)

{how_to}

Any engine, any OS: fill in only the files a game folder is missing
    python3 install.py --game /path/to/game
Existing files are never overwritten.

Other options
    python3 install.py --dest FOLDER     copy the pack to FOLDER
    python3 install.py --dry-run         show what would change
    python3 install.py --uninstall       undo everything this installer did

LICENSE
The images are dedicated to the public domain under CC0-1.0; install.py is MIT
licensed. See LICENSE.txt. Source, provenance and verification records:
https://github.com/Teloxico/SuperRTP
"""


def read_version() -> str:
    with open(VERSION_FILE, encoding="utf-8") as f:
        return f.read().strip()


def how_to(engine: str) -> str:
    if engine in RGSS:
        rgss, rtp_name = RGSS[engine]
        return HOW_TO["rmxp"].format(rgss=rgss, rtp_name=rtp_name)
    return HOW_TO[engine]


def license_text() -> str:
    with open(os.path.join(REPO_ROOT, "legal", "CC0-1.0.txt"), encoding="utf-8") as f:
        cc0 = f.read()
    with open(os.path.join(REPO_ROOT, "LICENSE"), encoding="utf-8") as f:
        mit = f.read()
    return ("The image files under rtp/ are dedicated to the public domain under CC0-1.0:\n\n" + cc0 +
            "\n\n----------------------------------------------------------------------\n\n"
            "install.py is licensed under the MIT License:\n\n" + mit)


def pack_metadata(pack: str, entries: list, manifest_sha: str, version: str) -> dict:
    first = entries[0]
    sources = {}
    for e in entries:
        sources[e["visual_source"]] = sources.get(e["visual_source"], 0) + 1
    return {
        "schema_version": 1,
        "pack": pack,
        "version": version,
        "engine": first["engine"],
        "engine_name": ENGINE_NAMES[first["engine"]],
        "locale": first["locale"],
        "license": "CC0-1.0",
        "source_manifest": "artifacts/generation/full-inventory/v2/manifest.json",
        "source_manifest_sha256": manifest_sha,
        "visual_sources": dict(sorted(sources.items())),
        "audio": "not included",
        "files": {e["path"]: e["sha256"] for e in sorted(entries, key=lambda e: e["path"])},
    }


def _add(archive: zipfile.ZipFile, name: str, data: bytes, executable: bool = False) -> None:
    info = zipfile.ZipInfo(name, ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (0o100755 if executable else 0o100644) << 16
    info.create_system = 3   # Unix, so the permission bits above are honoured
    archive.writestr(info, data, compresslevel=9)


def build_archive(pack: str, entries: list, root: str, manifest_sha: str, version: str, out_dir: str) -> str:
    meta = pack_metadata(pack, entries, manifest_sha, version)
    top = f"SuperRTP-{pack}"
    path = os.path.join(out_dir, f"SuperRTP-{pack}-{version}.zip")
    readme = README.format(pack=pack, version=version, engine_name=meta["engine_name"],
                           locale=LOCALE_NAMES[meta["locale"]], file_count=len(meta["files"]), how_to=how_to(meta["engine"]))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        with open(INSTALLER, "rb") as f:
            _add(archive, f"{top}/install.py", f.read(), executable=True)
        _add(archive, f"{top}/LICENSE.txt", license_text().encode())
        _add(archive, f"{top}/README.txt", readme.encode())
        _add(archive, f"{top}/superrtp-pack.json", (json.dumps(meta, indent=2, ensure_ascii=False) + "\n").encode())
        for e in sorted(entries, key=lambda e: e["path"]):
            with open(os.path.join(root, e["output"]), "rb") as f:
                data = f.read()
            if hashlib.sha256(data).hexdigest() != e["sha256"]:
                raise ValueError(f"{e['output']} does not match the manifest")
            _add(archive, f"{top}/rtp/{e['path']}", data)
    with open(path, "wb") as f:
        f.write(buffer.getvalue())
    return path


def main():
    parser = argparse.ArgumentParser(description="Package the verified packs as per-pack installable archives")
    parser.add_argument("--pack", action="append", help="only these packs (repeatable)")
    parser.add_argument("--out", default=os.path.join(REPO_ROOT, "dist"))
    parser.add_argument("--skip-check", action="store_true", help="skip the full pack verification (tests only)")
    args = parser.parse_args()

    spec = inventory.load_spec()
    if not args.skip_check:
        inventory.verify(spec, inventory.build_plan(spec))
    root = os.path.join(REPO_ROOT, spec["output_root"])
    manifest_path = os.path.join(root, "manifest.json")
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    by_pack = {}
    for e in manifest["entries"]:
        by_pack.setdefault(e["pack"], []).append(e)
    unknown = set(args.pack or []) - set(by_pack)
    if unknown:
        sys.exit(f"Unknown packs: {sorted(unknown)}; available: {sorted(by_pack)}")
    version = read_version()
    os.makedirs(args.out, exist_ok=True)
    manifest_sha = sha256_file(manifest_path)
    sums = []
    for pack in sorted(args.pack or by_pack):
        path = build_archive(pack, by_pack[pack], root, manifest_sha, version, args.out)
        sums.append(f"{sha256_file(path)}  {os.path.basename(path)}")
        print(f"{os.path.basename(path)}: {len(by_pack[pack])} files, {os.path.getsize(path) / 1e6:.1f} MB")
    with open(os.path.join(args.out, "SHA256SUMS"), "w", encoding="utf-8") as f:
        f.write("\n".join(sums) + "\n")


if __name__ == "__main__":
    main()
