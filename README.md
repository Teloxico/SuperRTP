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

SuperRTP maintains **one canonical source of truth** for compatibility and creative assets. Engine-specific RTP packs are generated artifacts rather than manually maintained independent packs:

```
Canonical Source Asset (Neutral RGBA raw + metadata)
        │
        ▼
Provenance Record (Licensing & Clean-Room Attestation)
        │
        ▼
Semantic Identity (Neutral Asset Specification & Geometry)
        │
        ▼
Compatibility Slot Mapping (Target Engine Slots & Aliases)
        │
        ▼
Deterministic Target Builder (Format, Palette Quantization & Chunk Encoding)
        │
        ▼
Engine-Specific Target Pack (`generated/<target>/`)
        │
        ▼
Runtime Verification (EasyRPG Player, mkxp-z, WOLF tools)
```

See [docs/architecture.md](docs/architecture.md) for full architectural specifications and compatibility models.

## Current Status: Phase 1 Vertical Slice (Hardened)

The Phase 1 vertical slice is implemented, hardened, and verified for **RPG Maker 2000 CharSet** compatibility:
- **Canonical Asset:** `test.calibration.walking-character`
  - Neutral 32-bit RGBA source ([`registry/assets/test_calibration_walking_character.rgba`](registry/assets/test_calibration_walking_character.rgba)) and preview ([`test_calibration_walking_character_master.png`](registry/assets/test_calibration_walking_character_master.png)).
  - 100% synthetic geometric primitives (directional chevrons, step markers, frame boundary calibration ticks).
- **Physical CharSet Geometry & Direction Rows:**
  - Strict RM2000 layout: 288×256 pixels, 4×2 character grid (8 characters, 72×128 px), 3×4 frame cells (24×32 px).
  - Physical row ordering (verified against EasyRPG upstream `game_character.h` enum `Up=0, Right=1, Down=2, Left=3`):
    - **Row 0**: Facing **Up** (`^`)
    - **Row 1**: Facing **Right** (`>`)
    - **Row 2**: Facing **Down** (`v`)
    - **Row 3**: Facing **Left** (`<`)
- **Deterministic Transformation:**
  - `tools/build_target.py` transforms canonical neutral RGBA into strict 8-bit indexed PNG (Color Type 3, $\le 256$ colors).
  - Preserves index 0 as transparent background color, and includes `tRNS` chunk for modern tool compatibility.
  - Generates byte-for-byte reproducible targets (`SOURCE_DATE_EPOCH` supported, static default timestamp).
- **Slot Mapping:**
  - Maps to `CharSet/Actor1.png` with official aliases derived from EasyRPG `rtp_table.cpp` (`actor1.png`, `Chara1.png`, `chara1.png`, `主人公1.png`).
  - RM2003-only alias (`Hero1.png`) is correctly excluded from RM2000 mapping.
- **Runtime & Visual Verification:**
  - Executed in EasyRPG Player 0.8.1.1 against a minimal clean-room game fixture ([`tests/fixtures/rm2000_min/`](tests/fixtures/rm2000_min)).
  - Replayed deterministic turning input across all 4 directions with verified clean logs.
  - All 4 directional runtime states visually inspected and verified in [`artifacts/runtime/rm2000/charset/`](artifacts/runtime/rm2000/charset/):
    - `rm2000_charset_down.png`: Character facing Down (`v`)
    - `rm2000_charset_left.png`: Character facing Left (`<`)
    - `rm2000_charset_up.png`: Character facing Up (`^`)
    - `rm2000_charset_right.png`: Character facing Right (`>`)
  - Isolated negative control verified (`rm2000_charset_negative_control.png` logs exactly `Image not found: CharSet/Actor1`).

## Repository Layout

```
├── .agents/          # Workspace verification skills
├── artifacts/
│   └── runtime/      # Verified real runtime screenshots and logs
├── docs/             # Technical architecture and research specifications
├── generated/        # Built runtime packages (gitignored)
├── legal/            # Legal documentation and clean-room policies
├── registry/
│   ├── assets/       # Canonical source assets (raw RGBA + metadata)
│   ├── provenance/   # Clean-room provenance sidecars and attestations
│   └── slots/        # Target engine slot mappings
├── schemas/          # JSON schemas for assets, provenance, and slots
├── tests/
│   ├── fixtures/     # Clean-room game fixtures and fixture_manifest.json
│   └── test_vertical_slice.py # Automated test suite
└── tools/            # Generators, target builders, and validators
```

## Verification & Build Commands

### 1. Run Automated Test Suite
```bash
SUPERRTP_REQUIRE_RUNTIME=1 python3 tests/test_vertical_slice.py
```
Executes 10 mechanical checks:
1. Canonical master RGBA and preview deterministic reproducibility
2. Target PNG structural compliance (288×256, 8-bit indexed, color type 3, index 0 transparent)
3. Provenance schema completeness and clean-room attestations
4. Target builder byte-for-byte reproducibility across clean runs and RM2000 slot accuracy
5. Validator aggressive rejection of corrupted / invalid assets
6. JSON schema validation on all registry metadata
7. Clean-room fixture binary and source hash integrity against `fixture_manifest.json`
8. Headless EasyRPG Player positive control (clean resolution without missing asset warnings)
9. Headless EasyRPG Player negative control (isolated `Image not found: CharSet/Actor1` failure)
10. Evidence chain cryptographic integrity and 4-direction runtime verification screenshots

### 2. Generate Clean-Room Fixture Graphics
```bash
python3 tools/generate_fixture_graphics.py
```
Deterministically generates fallback `ChipSet.png` and `System.png` for the test fixture from geometric primitives using pure Python standard library.

### 3. Generate Canonical Asset
```bash
python3 tools/generate_calibration_charset.py
```

### 4. Build RM2000 Target Pack
```bash
python3 tools/build_target.py --target rm2000 --clean
```

### 5. Validate Target Pack
```bash
python3 tools/validate_target.py --target rm2000
```

### 6. Runtime Verification & Evidence Verification (EasyRPG Player)
```bash
# Verify existing evidence chain, screenshot hashes, and logs:
python3 tools/verify_runtime.py --verify

# Or execute full live replay in EasyRPG under virtual X11, capture screenshots, and regenerate evidence:
python3 tools/verify_runtime.py --run-replay
```
Generates [`artifacts/runtime/rm2000/charset/verification_evidence.json`](artifacts/runtime/rm2000/charset/verification_evidence.json) cryptographically binding engine version, target manifest hash, fixture manifest hash, replay file hash, and screenshot hashes.

## Clean-Room Policy & Licensing

- Code, build tooling, validators, and schemas are licensed under the **MIT License** ([`LICENSE`](LICENSE)).
- Test calibration assets are dedicated to the public domain under **CC0-1.0 Universal**.
- See [legal/CLEAN_ROOM_POLICY.md](legal/CLEAN_ROOM_POLICY.md) for strict contributor clean-room invariants.
