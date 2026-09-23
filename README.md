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

> **Early stage.** The pipeline and its verification exist, but the actual replacement
> art does not yet. Packs built today are not usable for playing real games.

**Working:**
- **Builds for all six engines:** one set of canonical assets is transformed into all
  six engine formats, and the builds are deterministic (byte-for-byte reproducible).
- **Every output is checked in the real engine:** it is launched headlessly, and the
  on-screen result is checked pixel by pixel.
- **Negative controls:** each is a run with the asset removed, and it must show the
  engine's own missing-file error.
- **Evidence files:** they bind every hash, log and screenshot. Changing any recorded
  field makes verification fail.

**In progress:**
- **Replacement art for the whole inventory:** a local FLUX.2 [klein] 4B pipeline
  (Apache-2.0) is drawing original art for all 5,672 inventoried paths from our own art
  direction. Deterministic code turns it into the exact frame grids and formats. The
  resulting packs are candidates: they are not yet emitted by the target builder. See
  [docs/asset-generation.md](docs/asset-generation.md).

**Not there yet:**
- **Active assets:** the target builder still ships only two synthetic calibration
  images. One is a walking character sheet made of arrows and markers; the other is a
  map tileset.
- **Slots:** only the calibration filename slots are mapped to assets. The exhaustive
  upstream filename inventories now exist, but they are planning inputs rather than
  fake mappings to replacements that have not been created.
- **Audio:** music and sound are procedural placeholders. Candidate open audio models
  are listed in [docs/asset-generation.md](docs/asset-generation.md).
- **Known issue:** see [docs/known-issues.md](docs/known-issues.md).

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
              upstream-assets/ (filename-only replacement backlog)
schemas/      JSON schemas for assets, provenance and slot maps
tools/        builder, validator, transforms, runtime drivers and verifiers
tests/        test suites and clean-room engine fixtures (tests/fixtures/)
artifacts/    committed runtime evidence (screenshots, logs, evidence JSON)
generated/    build output (git-ignored)
docs/         architecture, engine facts, per-slice specs, known issues
legal/        clean-room policy
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
  model choice, art direction, provenance and known limits.
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
- **Calibration assets:** CC0-1.0.
- **Engines used only for verification, not distributed here:**
  - EasyRPG Player (GPLv3);
  - mkxp-z (GPLv2);
  - WOLF RPG Editor `Game.exe` (its own terms).
