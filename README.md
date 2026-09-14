# SuperRTP

A standalone clean-room compatibility and open-resource project for legacy RPG engines.

## Overview

SuperRTP provides drop-in compatible, independently licensed assets for legacy RPG engines without containing or deriving from proprietary Runtime Package (RTP) creative material.

Target engines:
- RPG Maker 2000 (`rm2000`)
- RPG Maker 2003 (`rm2003`)
- RPG Maker XP (`rmxp`)
- RPG Maker VX (`rmvx`)
- RPG Maker VX Ace (`rmvxace`)
- WOLF RPG Editor (`wolf`)

## Core Architecture

Rather than maintaining six independent sets of artistic assets, SuperRTP uses a unified metadata-driven build pipeline:

```
Canonical Source Asset
        │
        ▼
Provenance Record (Licensing & Clean-Room Attestation)
        │
        ▼
Semantic Identity (Neutral Asset Specification)
        │
        ▼
Compatibility Slot Mapping (Target Engine Slots & Aliases)
        │
        ▼
Deterministic Target Builder (Format & Palette Conversion)
        │
        ▼
Engine-Specific Target Pack (`generated/<target>/`)
        │
        ▼
Runtime Verification (EasyRPG Player, mkxp-z, WOLF tools)
```

## Current Status: Phase 1 Vertical Slice

The Phase 1 vertical slice is implemented and verified for **RPG Maker 2000 CharSet** compatibility:
- **Canonical Asset:** `test.calibration.walking-character` ([`registry/assets/test_calibration_walking_character.png`](registry/assets/test_calibration_walking_character.png))
  - 100% synthetic geometric primitives (directional arrows, step markers, calibration ticks).
  - Exact 288×256 8-bit indexed PNG (Color Type 3, $\le 256$ colors, index 0 transparent via `tRNS`).
- **Slot Mapping:** Maps to `CharSet/Actor1.png` with aliases (`Hero1.png`, `actor1.png`, `hero1.png`, `chara1.png`, `主人公1.png`).
- **Runtime Verification:** Executed and visually verified in EasyRPG Player 0.8.1.1 against a minimal clean-room RM2000 game fixture ([`tests/fixtures/rm2000_min/`](tests/fixtures/rm2000_min)). Includes verified negative-control proof (`--no-rtp`).

## Repository Layout

```
├── .agents/          # Workspace verification skills
├── artifacts/        # Captured runtime screenshots and evidence
├── docs/             # Technical specifications and research documents
├── generated/        # Built runtime packages (gitignored)
├── legal/            # Legal documentation and clean-room policies
├── registry/
│   ├── assets/       # Canonical source assets and asset metadata
│   ├── provenance/   # Clean-room provenance sidecars and hashes
│   └── slots/        # Target engine slot mappings
├── schemas/          # JSON schemas for assets, provenance, and slots
├── tests/
│   ├── fixtures/     # Clean-room game fixtures (liblcf generated)
│   └── test_vertical_slice.py # Automated test suite
└── tools/            # Generators, target builders, and validators
```

## Verification & Build Commands

### 1. Run Automated Test Suite
```bash
python3 tests/test_vertical_slice.py
```
Executes 7 mechanical checks including byte reproducibility, PNG format compliance, clean-room provenance attestation, builder execution, corrupted asset rejection, and real EasyRPG Player headless positive & negative controls.

### 2. Generate Canonical Asset
```bash
python3 tools/generate_calibration_charset.py
```

### 3. Build RM2000 Target Pack
```bash
python3 tools/build_target.py --target rm2000 --clean
```
Outputs to `generated/rm2000/` with a verifiable `manifest.json`.

### 4. Validate Target Pack
```bash
python3 tools/validate_target.py --target rm2000
```
Mechanically verifies PNG chunks (`IHDR`, `PLTE`, `tRNS`, `IDAT`, `IEND`), 288×256 dimensions, color type 3, palette size, index 0 transparency, and provenance completeness.

### 5. Runtime Execution (EasyRPG Player)
```bash
# Positive test (RTP resolved):
easyrpg-player --project-path tests/fixtures/rm2000_min --rtp-path generated/rm2000 --engine rpg2k --new-game --disable-audio

# Negative control (Missing asset fallback):
easyrpg-player --project-path tests/fixtures/rm2000_min --no-rtp --engine rpg2k --new-game --disable-audio
```

## Clean-Room Invariant

SuperRTP contains zero proprietary RTP creative content. All assets are either deterministically generated geometric calibration fixtures or verified permissive open-source material with documented provenance.
