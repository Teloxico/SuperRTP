# Installing a pack

Each engine's pack is a separate archive, `SuperRTP-<pack>-<version>.zip`, built by
`tools/release/package_release.py`. It holds `install.py` (Python 3.8+, standard library
only), `README.txt`, `LICENSE.txt`, `superrtp-pack.json` (the SHA-256 of every file) and
`rtp/` (the files at their engine paths). Unzip it and run `install.py`; the pack's
`README.txt` has the commands for its engine.

| Pack | Engine | File names |
|---|---|---|
| `rm2000-en`, `rm2000-ja` | RPG Maker 2000 | English, Japanese |
| `rm2003-en`, `rm2003-ja`, `rm2003-zh-tw` | RPG Maker 2003 | English, Japanese, Traditional Chinese |
| `rmxp` | RPG Maker XP (RGSS1) | as the original |
| `rmvx` | RPG Maker VX (RGSS2) | as the original |
| `rmvxace` | RPG Maker VX Ace (RGSS3) | as the original |
| `wolf` | WOLF RPG Editor | as the base distribution |

EasyRPG Player maps a game's requested file name to the installed RTP's names through
its lookup table (`src/rtp_table.cpp`), so for EasyRPG one pack per engine is enough
whatever the game's language. The original Windows runtimes look files up by name, so a
Japanese game there needs the `-ja` pack.

## Where each runtime looks, and what `install.py` does

| Runtime | Where it finds an RTP | `install.py` | Source | Verified |
|---|---|---|---|---|
| EasyRPG Player (2000/2003), Linux, macOS, BSD | `$XDG_DATA_HOME/rtp/2000\|2003` (default `~/.local/share/...`), then `$XDG_DATA_DIRS/rtp/...`. Built with `USE_XDG_RTP` on every non-console, non-Windows platform, macOS included | default: copies to `$XDG_DATA_HOME/rtp/<version>` | `src/filefinder_rtp.cpp` and `src/system.h` at tag `0.8.1.1` | Linux: EasyRPG 0.8.1.1 finds the installed pack with no RTP option (runtime gate `installed-xdg`). macOS: **UNVERIFIED** in the engine; the installer runs in CI on macOS |
| EasyRPG Player (2000/2003), Windows | registry value `Software\ASCII\RPG2000` `RuntimePackagePath` (2000), `Software\Enterbrain\RPG2003` `RUNTIMEPACKAGEPATH` (2003), also the `KADOKAWA` keys; HKCU first, then HKLM, 32-bit view | default: copies to `%LOCALAPPDATA%\SuperRTP\packs\<pack>` and writes the HKCU value; `--register machine` writes HKLM | `src/filefinder_rtp.cpp`, `src/registry.cpp` at `0.8.1.1` | Same key names verified through EasyRPG's Wine-registry reader, which uses the same lookup (gate `installed-wine-user`, `installed-wine-machine`). Registry writes verified on Windows in CI. EasyRPG on Windows itself: **UNVERIFIED** |
| RPG_RT.exe (original 2000/2003 runtime), Windows | the registry values above. EasyRPG's source shows the original installer writing HKLM (`Wow6432Node\ASCII\RPG2000`) | `--register machine` (administrator) | EasyRPG `src/registry_wine.cpp` comment | **UNVERIFIED**: the original runtime is not run here |
| RGSS `Game.exe` (XP/VX/VX Ace), Windows | `Game.ini` names the RTP (`RTP1=Standard`, `RTP=RPGVX`, `RTP=RPGVXAce`); the path is the string value of that name in `HKLM\SOFTWARE\Enterbrain\RGSS\RTP`, `...\RGSS2\RTP`, `...\RGSS3\RTP` (32-bit view, so `Wow6432Node` on 64-bit Windows) | `--register machine` (administrator) writes that value | RGSS reference manuals, "RGSS Specifications", RTP section (XP, VX and VX Ace help files) | Registry writes verified on Windows in CI. The RGSS runtime itself: **UNVERIFIED** (not run here) |
| mkxp-z (XP/VX/VX Ace), any OS | the `"RTP"` list of `mkxp.json` (next to the game, or in the user data folder). Folders and `.zip` files are accepted | `--mkxp-json FILE` copies the pack to the user data folder and appends it to that list; a file with comments is left untouched | `mkxp.json` sample and `src/config.cpp` at the pinned commit `826929e` | Linux: mkxp-z loads every image of each pack through the list `install.py` wrote (gate `scan`) |
| Windows runtimes under Wine | the same registry values inside the Wine prefix | `--wine-prefix DIR` (with `--register machine` for HKLM) writes them with Wine's `reg.exe`; paths become `Z:\...` | Wine `reg` | Verified (gate `installed-wine-*`) |
| WOLF RPG Editor | no shared RTP: files resolve relative to the game | `--game DIR` fills only the missing files of a game folder | docs/engine-facts.md | Game.exe draws a generated CharaChip (gate `wolf`) |
| Any engine | a game folder is searched before the RTP | `--game DIR` | | Installer tested on all three OSes in CI |

## Safety

- **Files:** an existing file is never overwritten. Files that differ from the pack are
  reported and kept.
- **Registry:** an existing registry value is never replaced. If an RTP is already
  registered, the installer says so and leaves it; use `--game` for that game instead.
- **Integrity:** every pack file is checked against `superrtp-pack.json` before anything
  is copied, so a corrupted download is refused.
- **Uninstall:** every change is recorded under `<user data>/SuperRTP/installs/`.
  `--uninstall` removes exactly what was added: files only while unchanged, registry
  values only while they still hold the installed path, and the added `mkxp.json` entry.

## Releases

`python3 tools/release/package_release.py` writes the archives and `SHA256SUMS` to
`dist/`. It refuses to package unless `generate_full_inventory.py --check` passes and the
runtime gate report passed every case on the same manifest.
