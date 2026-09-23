# SuperRTP

**Clean-room, openly licensed replacement runtime packages (RTPs) for legacy RPG engines.**

Many games made with RPG Maker or WOLF RPG Editor expect the engine's Runtime Package
(RTP) to be installed: a proprietary set of character sprites, tilesets, music and sound
effects looked up by filename. SuperRTP aims to provide drop-in packs that fill the same
slots with independently created, redistributable assets. It contains **zero
proprietary RTP content**, and nothing in it is derived from one.

| Target | Engine | Verified in |
|---|---|---|
| `rm2000` | RPG Maker 2000 | EasyRPG Player 0.8.1.1 |
| `rm2003` | RPG Maker 2003 | EasyRPG Player 0.8.1.1 |
| `rmxp` | RPG Maker XP (RGSS1) | mkxp-z, pinned commit `826929e` |
| `rmvx` | RPG Maker VX (RGSS2) | mkxp-z, pinned commit `826929e` |
| `rmvxace` | RPG Maker VX Ace (RGSS3) | mkxp-z, pinned commit `826929e` |
| `wolf` | WOLF RPG Editor 3 | official `Game.exe` 3.717 under Wine |

## Project status

> **Images: generated and engine-checked. Audio: not included.** Version 0.1.0.

**Working:**
- **Replacement art for every image slot:** 2,934 image paths across all six engines,
  drawn by a local FLUX.2 [klein] 4B model (Apache-2.0) from this project's own art
  direction. Deterministic code turns the drawings into the exact frame grids, sizes and
  formats each engine expects. Characters are drawn as separate front, side and back
  views, so every facing direction reads correctly. See
  [docs/asset-generation.md](docs/asset-generation.md).
- **Separate, installable packs per engine:** each pack is its own archive with an
  `install.py` that puts it where that engine's runtime looks for its RTP, on Windows,
  Linux and macOS. It never overwrites files or registry values, and it can uninstall
  cleanly. See [docs/installing.md](docs/installing.md).
- **Checked in the real engines:**
  - EasyRPG Player finds an installed pack on its own and draws the generated art.
  - mkxp-z loads every image of the XP, VX and VX Ace packs at the right size.
  - WOLF's `Game.exe` draws a generated character cell by cell.
- **Calibration slices:** the original verification slices, synthetic images with
  pixel-exact checks and negative controls in every engine, still guard the transforms
  and the engine drivers. See [docs/verified-slices.md](docs/verified-slices.md).

**Not there yet:**
- **Audio:** music and sound effects are not generated. The 2,738 inventoried audio
  paths are listed as a backlog in the pack manifest.
- **Animation:** walking steps are a small synthesised leg offset, not drawn strides.
  Battle poses are transforms of one sprite.
- **Tilesets:** these are filled with generated material textures, not hand-designed
  tile layouts, so maps built for the original tiles will look patchy.
- **Unverified runtimes:** the original Windows runtimes (RPG_RT.exe, the RGSS
  `Game.exe`) and EasyRPG on Windows and macOS were not run. The installer writes the
  registry values and folders their documentation and source name, and CI tests those
  writes on Windows and macOS.
- **Known issues:** see [docs/known-issues.md](docs/known-issues.md).

## Install a pack

Download the archive for your engine, unzip it, and run its installer (Python 3.8+):

```bash
python3 install.py
```

This one command covers EasyRPG Player on Linux and macOS, and RPG Maker 2000/2003 games
on Windows. For RPG Maker XP, VX and VX Ace, and for WOLF, the pack's `README.txt` gives
the one extra option to use:
- `--mkxp-json` for mkxp-z;
- `--register machine` for a game's own Windows `Game.exe`;
- `--game` to fill in a single game folder.

[docs/installing.md](docs/installing.md) lists where every runtime looks, with sources.

## How it works

Engine packs are *generated*. They are never edited by hand. Everything flows from one
canonical source:

```
canonical asset (registry/assets/)            neutral RGBA + metadata
  -> provenance record (registry/provenance/)   who made it, under what license
  -> slot mapping (registry/slots/<target>.json) which engine filenames it fills
  -> deterministic transform (tools/transforms.py) engine layout, palette, PNG encoding
  -> target pack (generated/<target>/)          + manifest.json
  -> runtime verification (tools/verify_*.py)   real engine, screenshots, evidence
```

A slot (a filename an engine looks up) and an asset (a picture SuperRTP owns) are kept
separate. Filling `CharSet/Actor1.png` only satisfies a lookup. It does not recreate
the proprietary image that historically lived there. See
[docs/architecture.md](docs/architecture.md) for the design.

## Quick start

The build and validation tools need only **Python 3.12+** (standard library, no
packages).

```bash
python3 tools/build_target.py --target rm2000 --clean   # -> generated/rm2000/
python3 tools/validate_target.py --target rm2000
```

Replace `rm2000` with any target from the table. To use a pack with EasyRPG Player,
point it at the output: `easyrpg-player --rtp-path generated/rm2000`.

## Testing

```bash
cd tests && python3 -m unittest discover -v
```

| Suite | Covers |
|---|---|
| `test_foundation.py` | PNG codec; schemas; registry and provenance; frame transforms for every engine layout, checked against an independent oracle; reproducible builds; validator rejections |
| `test_fixtures.py` | Fixture manifests; byte-identical regeneration of fixture and calibration graphics |
| `test_runtime_evidence.py` | Committed evidence verifies. Every evidence field is tamper-checked. Altered screenshot pixels are rejected. A fresh live capture through each real engine must verify. |
| `test_full_inventory_generation.py` | Inventory plan counts, clean-room and license gates, authored prompts, view references, deterministic encoding |
| `test_installer.py` | The pack installer on the OS it runs on (CI: Windows, macOS, Linux, Python 3.8 and 3.12), including Windows registry writes |

Live tests skip when an engine is not installed. With `SUPERRTP_REQUIRE_RUNTIME=1`, as
in CI, a missing engine is a failure instead. The live runs need:
- **All engines:** Xvfb, ffmpeg and xdotool.
- **RM2000/2003:** EasyRPG Player 0.8.1.1.
- **XP/VX/VX Ace:** mkxp-z (build it with `tools/install_mkxp_z_ci.sh`).
- **WOLF:** Wine with 32-bit support and `Game.exe`. Install `Game.exe` with
  `tools/install_wolf_ci.sh`; the script checks its SHA-256.

Live captures write to temporary directories, so committed artifacts are never
modified.

### Runtime evidence

Each slice has committed evidence under `artifacts/runtime/<target>/<category>/`: the
screenshots, the engine logs, and a `verification_evidence.json` that binds them to the
exact source, pack, fixture and engine version.

```bash
python3 tools/verify_runtime.py --target all --verify           # RM2000/2003 CharSet
python3 tools/verify_chipset_runtime.py --target all --verify   # RM2000/2003 ChipSet
python3 tools/verify_rmxp_runtime.py --verify
python3 tools/verify_rmvx_runtime.py --verify
python3 tools/verify_rmvxace_runtime.py --verify
python3 tools/verify_wolf_runtime.py --verify
```

Replace `--verify` with `--run-capture` to re-capture through the live engine. Add
`--artifacts-dir <dir>` to write somewhere other than the committed artifacts.

## Repository layout

```
registry/     assets/ (canonical sources), provenance/, slots/ (mapped outputs),
              upstream-assets/ (the filename inventory every pack covers)
specs/        generation specs and the art direction (all prompt text)
schemas/      JSON schemas for assets, provenance and slot maps
tools/        builder, validator, transforms, runtime drivers and verifiers
  asset_generation/   FLUX planning, generation, structuring, pack encoding
  release/            install.py (shipped in every pack) and the release packager
tests/        test suites and clean-room engine fixtures (tests/fixtures/)
artifacts/    committed runtime evidence; generation manifests and runtime-gate reports
generated/    calibration build output (git-ignored)
dist/         release archives (git-ignored)
docs/         architecture, engine facts, generation, installing, known issues
legal/        clean-room policy, CC0 legal code
```

Most `tools/` modules are shared:
- **`png_utils`:** deterministic PNG encoding and decoding.
- **`transforms`:** sheet layouts per engine.
- **`registry`:** slot and provenance lookups.
- **`evidence`:** evidence checks.
- **`runtime_harness`:** Xvfb, recording and input.
- **Engine drivers:** `easyrpg_runtime`, `mkxp_runtime`, `wolf_runtime`.

The `verify_*.py` scripts are thin per-slice verifiers on top of them.

## Documentation

- [docs/architecture.md](docs/architecture.md): design, pipeline and per-engine layout.
- [docs/engine-facts.md](docs/engine-facts.md): researched engine behavior, with
  sources (lookup tables, sheet layouts, transparency, animation order).
- [docs/upstream-asset-inventory.md](docs/upstream-asset-inventory.md): every bundled
  creative-media path in the six pinned upstream distributions, with official
  RM2000/RM2003 locale aliases and source hashes.
- [docs/asset-generation.md](docs/asset-generation.md): the FLUX.2 generation pipeline,
  model choice, art direction, provenance, runtime gate and known limits.
- [docs/installing.md](docs/installing.md): the packs, where each runtime looks for an
  RTP (with sources and verification status), and what the installer changes.
- [docs/verified-slices.md](docs/verified-slices.md): detailed specification and
  evidence for each slice.
- [docs/known-issues.md](docs/known-issues.md): open problems and what is known about
  them.
- [legal/CLEAN_ROOM_POLICY.md](legal/CLEAN_ROOM_POLICY.md): rules for anything entering
  the repository.

## Contributing

Read [legal/CLEAN_ROOM_POLICY.md](legal/CLEAN_ROOM_POLICY.md) and
[AGENTS.md](AGENTS.md) first. In short:
- **Never use proprietary RTP material,** not as a source and not as a reference, and
  never in a derived form.
- **Every asset needs a provenance record** with a redistribution-compatible license.
  "Free for games" is not enough.
- **Engine behavior claims need a source.** Record it in `docs/engine-facts.md`.
- **A change to a pack isn't done until it has been verified in the real engine.**

## License

- **Code, tooling and schemas:** [MIT](LICENSE).
- **Generated pack images and calibration assets:** CC0-1.0
  ([legal/CC0-1.0.txt](legal/CC0-1.0.txt)).
- **Engines used only for verification, not distributed here:**
  - EasyRPG Player (GPLv3);
  - mkxp-z (GPLv2);
  - WOLF RPG Editor `Game.exe` (its own terms).
