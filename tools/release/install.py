#!/usr/bin/env python3
"""
SuperRTP pack installer. Ships inside every pack archive next to superrtp-pack.json and
rtp/ (the pack's files). Needs only Python 3.8+ (standard library) on Windows, Linux or
macOS.

    python3 install.py                      # install for this OS (see below)
    python3 install.py --game PATH          # fill missing files of one game folder instead
    python3 install.py --dest PATH          # copy the pack to PATH (no registration)
    python3 install.py --mkxp-json FILE     # also add the pack to an mkxp-z RTP list
    python3 install.py --register machine   # Windows: register for the official runtimes (administrator)
    python3 install.py --wine-prefix DIR    # register inside a Wine prefix (Linux/macOS)
    python3 install.py --uninstall          # undo everything this pack's installer recorded
    python3 install.py --dry-run            # print what would happen

Where each runtime looks for an RTP (sources in docs/installing.md):
  EasyRPG Player (2000/2003), Linux and macOS: $XDG_DATA_HOME/rtp/2000|2003
      (default ~/.local/share/rtp/...), found automatically. This is the default here.
  EasyRPG Player and RPG_RT.exe (2000/2003), Windows: registry value
      Software\\ASCII\\RPG2000 RuntimePackagePath / Software\\Enterbrain\\RPG2003
      RUNTIMEPACKAGEPATH (HKCU is written by default; --register machine writes HKLM like
      the original installers).
  RGSS Game.exe (XP/VX/VX Ace), Windows: HKLM Software\\Enterbrain\\RGSS|RGSS2|RGSS3\\RTP,
      value Standard|RPGVX|RPGVXAce. Needs --register machine (administrator).
  mkxp-z (XP/VX/VX Ace, any OS): the "RTP" list in mkxp.json (--mkxp-json).
  WOLF RPG Editor has no RTP: use --game on the game folder.

Safety rules: an existing file is never overwritten (files that differ are reported and
kept), an existing registry value is never replaced, and every change is recorded so
--uninstall removes exactly what this installer added (and only files still unchanged).
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PACK_JSON = os.path.join(HERE, "superrtp-pack.json")
PACK_FILES = os.path.join(HERE, "rtp")

# engine -> (EasyRPG version directory, registry registrations as (hive, key, value name))
ENGINES = {
    "rm2000": ("2000", [("HKCU", r"Software\ASCII\RPG2000", "RuntimePackagePath")]),
    "rm2003": ("2003", [("HKCU", r"Software\Enterbrain\RPG2003", "RUNTIMEPACKAGEPATH")]),
    "rmxp": (None, [("HKLM", r"Software\Enterbrain\RGSS\RTP", "Standard")]),
    "rmvx": (None, [("HKLM", r"Software\Enterbrain\RGSS2\RTP", "RPGVX")]),
    "rmvxace": (None, [("HKLM", r"Software\Enterbrain\RGSS3\RTP", "RPGVXAce")]),
    "wolf": (None, []),
}


class InstallError(Exception):
    pass


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_pack(pack_json=PACK_JSON, files_dir=PACK_FILES):
    """Reads superrtp-pack.json and checks every listed file against its SHA-256."""
    with open(pack_json, encoding="utf-8") as f:
        pack = json.load(f)
    if pack.get("engine") not in ENGINES:
        raise InstallError(f"Unknown engine in {pack_json}: {pack.get('engine')!r}")
    for rel, digest in pack["files"].items():
        path = os.path.join(files_dir, *rel.split("/"))
        if not os.path.isfile(path) or sha256_file(path) != digest:
            raise InstallError(f"Pack file missing or corrupted: {rel}. Re-download the pack.")
    return pack


def data_home(env=os.environ, platform=sys.platform):
    """Per-user data directory: %LOCALAPPDATA%, ~/Library/Application Support, or $XDG_DATA_HOME."""
    home = os.path.expanduser("~")
    if platform == "win32":
        return env.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
    if platform == "darwin":
        return os.path.join(home, "Library", "Application Support")
    return env.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")


def default_destination(pack, env=os.environ, platform=sys.platform):
    easyrpg_dir, _ = ENGINES[pack["engine"]]
    if easyrpg_dir and platform != "win32":
        # EasyRPG uses $XDG_DATA_HOME/rtp/<version> on every non-Windows desktop, macOS included.
        base = env.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
        return os.path.join(base, "rtp", easyrpg_dir)
    return os.path.join(data_home(env, platform), "SuperRTP", "packs", pack["pack"])


def record_path(pack, env=os.environ, platform=sys.platform):
    return os.path.join(data_home(env, platform), "SuperRTP", "installs", pack["pack"] + ".json")


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

def copy_files(pack, dest, dry_run, files_dir=PACK_FILES):
    """Copies files missing at `dest`. Returns (copied relative paths, kept differing files)."""
    copied, kept = [], []
    for rel, digest in sorted(pack["files"].items()):
        target = os.path.join(dest, *rel.split("/"))
        if os.path.exists(target):
            if sha256_file(target) != digest:
                kept.append(rel)
            continue
        if not dry_run:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copyfile(os.path.join(files_dir, *rel.split("/")), target)
        copied.append(rel)
    return copied, kept


def remove_files(dest, files, digests):
    """Removes recorded files that are unchanged, then empty directories they left behind."""
    removed, changed = 0, []
    for rel in files:
        target = os.path.join(dest, *rel.split("/"))
        if not os.path.exists(target):
            continue
        if sha256_file(target) != digests.get(rel):
            changed.append(rel)
            continue
        os.remove(target)
        removed += 1
        parent = os.path.dirname(target)
        while os.path.abspath(parent) != os.path.abspath(dest) and os.path.isdir(parent) and not os.listdir(parent):
            os.rmdir(parent)
            parent = os.path.dirname(parent)
    if os.path.isdir(dest) and not os.listdir(dest):
        os.rmdir(dest)
    return removed, changed


# ---------------------------------------------------------------------------
# Registry (native Windows through winreg; Wine prefixes through `wine reg`)
# ---------------------------------------------------------------------------

def windows_path_for_wine(path):
    """Wine maps drive Z: to the Unix root."""
    return "Z:" + os.path.abspath(path).replace("/", "\\")


class NativeRegistry:
    """HKCU/HKLM in the 32-bit view, which the 32-bit runtimes read (Wow6432Node on 64-bit Windows)."""

    def __init__(self):
        import winreg
        self.winreg = winreg
        self.hives = {"HKCU": winreg.HKEY_CURRENT_USER, "HKLM": winreg.HKEY_LOCAL_MACHINE}
        self.view = winreg.KEY_WOW64_32KEY

    def read(self, hive, key, name):
        try:
            with self.winreg.OpenKey(self.hives[hive], key, 0, self.winreg.KEY_READ | self.view) as handle:
                return self.winreg.QueryValueEx(handle, name)[0]
        except FileNotFoundError:
            return None

    def write(self, hive, key, name, value):
        try:
            with self.winreg.CreateKeyEx(self.hives[hive], key, 0, self.winreg.KEY_WRITE | self.view) as handle:
                self.winreg.SetValueEx(handle, name, 0, self.winreg.REG_SZ, value)
        except PermissionError as exc:
            raise InstallError(f"Writing {hive}\\{key} needs administrator rights: run the installer as administrator") from exc

    def delete(self, hive, key, name):
        with self.winreg.OpenKey(self.hives[hive], key, 0, self.winreg.KEY_SET_VALUE | self.view) as handle:
            self.winreg.DeleteValue(handle, name)

    def path_value(self, path):
        return os.path.abspath(path)


class WineRegistry:
    """The same registry values inside a Wine prefix, through Wine's reg.exe (/reg:32)."""

    def __init__(self, prefix, wine=None):
        self.prefix = os.path.abspath(prefix)
        self.wine = wine or shutil.which("wine") or shutil.which("wine64")
        if not self.wine:
            raise InstallError("--wine-prefix needs the `wine` command on PATH")

    def _reg(self, *args):
        env = dict(os.environ, WINEPREFIX=self.prefix, WINEDEBUG="-all")
        return subprocess.run([self.wine, "reg", *args, "/reg:32"], env=env, capture_output=True, text=True)

    def read(self, hive, key, name):
        result = self._reg("query", f"{hive}\\{key}", "/v", name)
        if result.returncode != 0:
            return None
        for line in result.stdout.splitlines():
            parts = line.split(None, 2)
            if len(parts) == 3 and parts[0].lower() == name.lower() and parts[1] == "REG_SZ":
                return parts[2]
        return None

    def write(self, hive, key, name, value):
        result = self._reg("add", f"{hive}\\{key}", "/v", name, "/t", "REG_SZ", "/d", value, "/f")
        if result.returncode != 0:
            raise InstallError(f"wine reg add failed: {(result.stdout + result.stderr).strip()}")

    def delete(self, hive, key, name):
        result = self._reg("delete", f"{hive}\\{key}", "/v", name, "/f")
        if result.returncode != 0:
            raise InstallError(f"wine reg delete failed: {(result.stdout + result.stderr).strip()}")

    def path_value(self, path):
        return windows_path_for_wine(path)


def registrations(pack, scope):
    """The registry values to write for `scope` ('user' or 'machine')."""
    result = []
    for hive, key, name in ENGINES[pack["engine"]][1]:
        if scope == "machine":
            hive = "HKLM"
        elif hive == "HKLM":
            continue   # the RGSS runtimes only read HKLM (--register machine)
        result.append((hive, key, name))
    return result


def register(pack, registry, dest, scope, dry_run):
    """Writes registrations whose value is not set yet. Returns (written, skipped messages)."""
    written, skipped = [], []
    value = registry.path_value(dest)
    for hive, key, name in registrations(pack, scope):
        current = registry.read(hive, key, name)
        if current is not None:
            if current.rstrip("\\/").lower() != value.rstrip("\\/").lower():
                skipped.append(f"{hive}\\{key} {name} already points to {current}; left unchanged")
            continue
        if not dry_run:
            registry.write(hive, key, name, value)
        written.append({"hive": hive, "key": key, "name": name, "value": value})
    return written, skipped


# ---------------------------------------------------------------------------
# mkxp-z configuration
# ---------------------------------------------------------------------------

def add_to_mkxp_json(path, dest, dry_run):
    """Adds `dest` to the RTP list of an mkxp.json. Returns True if the file changed."""
    config = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            text = f.read()
        try:
            config = json.loads(text) if text.strip() else {}
        except json.JSONDecodeError as exc:
            # mkxp-z accepts comments in mkxp.json; rewriting such a file would drop them.
            raise InstallError(f"{path} is not plain JSON (it may contain comments), so it is left untouched. "
                               f'Add "{os.path.abspath(dest)}" to its "RTP" list by hand.') from exc
    rtp = config.get("RTP", [])
    if not isinstance(rtp, list):
        raise InstallError(f'"RTP" in {path} is not a list')
    if os.path.abspath(dest) in rtp:
        return False
    if not dry_run:
        config["RTP"] = rtp + [os.path.abspath(dest)]
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
            f.write("\n")
    return True


def remove_from_mkxp_json(path, dest):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        config = json.load(f)
    rtp = [p for p in config.get("RTP", []) if p != os.path.abspath(dest)]
    config["RTP"] = rtp
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
        f.write("\n")


# ---------------------------------------------------------------------------
# Install / uninstall
# ---------------------------------------------------------------------------

def _load_record(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def install(pack, args, env=os.environ, platform=sys.platform, files_dir=PACK_FILES, registry=None, log=print):
    dest = os.path.abspath(args.game or args.dest or default_destination(pack, env, platform))
    rec_path = record_path(pack, env, platform)
    record = _load_record(rec_path) or {"pack": pack["pack"], "version": pack["version"], "installs": []}

    copied, kept = copy_files(pack, dest, args.dry_run, files_dir)
    log(f"{'Would copy' if args.dry_run else 'Copied'} {len(copied)} files to {dest}")
    if kept:
        log(f"Kept {len(kept)} existing files that differ from the pack (not overwritten), e.g. {kept[0]}")
    entry = {"destination": dest, "files": copied, "registry": [], "mkxp_json": []}

    scope = args.register
    if scope is None and platform == "win32" and not args.game and ENGINES[pack["engine"]][0]:
        scope = "user"      # RPG Maker 2000/2003 on Windows: registering is how runtimes find it
    if args.wine_prefix:
        registry = registry or WineRegistry(args.wine_prefix)
        scope = scope or "user"
    elif scope:
        if platform != "win32" and registry is None:
            raise InstallError("--register writes the Windows registry; on Linux/macOS use --wine-prefix")
        registry = registry or NativeRegistry()
    if scope and registry is not None:
        written, skipped = register(pack, registry, dest, scope, args.dry_run)
        for item in written:
            log(f"{'Would register' if args.dry_run else 'Registered'} {item['hive']}\\{item['key']} {item['name']} = {item['value']}")
        for message in skipped:
            log(message)
        if not registrations(pack, scope):
            log("This engine's runtimes do not read a per-user registry value; use --register machine (administrator)")
        entry["registry"] = [dict(w, wine_prefix=os.path.abspath(args.wine_prefix) if args.wine_prefix else None) for w in written]

    if args.mkxp_json:
        if add_to_mkxp_json(args.mkxp_json, dest, args.dry_run):
            entry["mkxp_json"].append(os.path.abspath(args.mkxp_json))
            log(f"Added {dest} to the RTP list of {args.mkxp_json}")

    if not args.dry_run and (entry["files"] or entry["registry"] or entry["mkxp_json"]):
        record["installs"].append(entry)
        os.makedirs(os.path.dirname(rec_path), exist_ok=True)
        with open(rec_path, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2)
            f.write("\n")
    if ENGINES[pack["engine"]][0] is None and not (args.game or args.mkxp_json or scope):
        log("Next step: point your runtime at this folder (mkxp-z: --mkxp-json; Windows RGSS: --register machine; "
            "WOLF: --game). See README.txt.")
    return entry


def uninstall(pack, env=os.environ, platform=sys.platform, registry_factory=None, log=print):
    rec_path = record_path(pack, env, platform)
    record = _load_record(rec_path)
    if not record:
        log(f"Nothing recorded for {pack['pack']}; nothing to remove")
        return
    for entry in reversed(record["installs"]):
        for mkxp_path in entry["mkxp_json"]:
            remove_from_mkxp_json(mkxp_path, entry["destination"])
            log(f"Removed {entry['destination']} from {mkxp_path}")
        for item in entry["registry"]:
            if registry_factory:
                registry = registry_factory(item)
            else:
                registry = WineRegistry(item["wine_prefix"]) if item.get("wine_prefix") else NativeRegistry()
            if registry.read(item["hive"], item["key"], item["name"]) == item["value"]:
                registry.delete(item["hive"], item["key"], item["name"])
                log(f"Unregistered {item['hive']}\\{item['key']} {item['name']}")
        removed, changed = remove_files(entry["destination"], entry["files"], pack["files"])
        log(f"Removed {removed} files from {entry['destination']}")
        if changed:
            log(f"Kept {len(changed)} files changed since installation, e.g. {changed[0]}")
    os.remove(rec_path)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Install or remove a SuperRTP pack")
    where = parser.add_mutually_exclusive_group()
    where.add_argument("--game", help="fill missing files of this game folder")
    where.add_argument("--dest", help="copy the pack to this folder")
    parser.add_argument("--register", choices=("user", "machine"),
                        help="Windows: register the install folder for the engine's runtimes")
    parser.add_argument("--wine-prefix", help="register inside this Wine prefix (Linux/macOS)")
    parser.add_argument("--mkxp-json", help="add the install folder to this mkxp-z mkxp.json RTP list")
    parser.add_argument("--uninstall", action="store_true", help="undo everything recorded for this pack")
    parser.add_argument("--dry-run", action="store_true", help="show what would change")
    args = parser.parse_args(argv)
    try:
        pack = load_pack()
        print(f"SuperRTP {pack['pack']} {pack['version']} ({pack['engine_name']})")
        if args.uninstall:
            uninstall(pack)
        else:
            install(pack, args)
    except InstallError as exc:
        sys.exit(f"Error: {exc}")


if __name__ == "__main__":
    main()
