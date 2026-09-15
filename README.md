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

## Current Status: Phase 1, 2 & 3 Cross-Target Vertical Slices (Hardened)

The compatibility slices are implemented, hardened, and verified for **cross-target compatibility** across both **RPG Maker 2000 (`rm2000`)** and **RPG Maker 2003 (`rm2003`)** for both **CharSet** and **ChipSet** categories from shared canonical source assets:

### 1. CharSet Walking Character Compatibility Slice
- **Single Canonical Asset:** `test.calibration.walking-character`
  - Neutral 32-bit RGBA source ([`registry/assets/test_calibration_walking_character.rgba`](registry/assets/test_calibration_walking_character.rgba)) and preview ([`test_calibration_walking_character_master.png`](registry/assets/test_calibration_walking_character_master.png)).
  - 100% synthetic geometric primitives (directional chevrons, step markers, frame boundary calibration ticks).
- **Physical CharSet Geometry & Direction Rows:**
  - Strict 2k-family layout: 288×256 pixels, 4×2 character grid (8 characters, 72×128 px), 3×4 frame cells (24×32 px).
  - Physical row ordering (verified against EasyRPG upstream `game_character.h` enum `Up=0, Right=1, Down=2, Left=3`):
    - **Row 0**: Facing **Up** (`^`)
    - **Row 1**: Facing **Right** (`>`)
    - **Row 2**: Facing **Down** (`v`)
    - **Row 3**: Facing **Left** (`<`)
- **Deterministic Cross-Target Transformation:**
  - `tools/build_target.py` transforms canonical neutral RGBA into strict 8-bit indexed PNG (Color Type 3, $\le 256$ colors).
  - Produces bit-for-bit identical primary `Actor1.png` across both `rm2000` and `rm2003` targets.
  - Preserves index 0 as transparent background color, and includes `tRNS` chunk for modern tool compatibility.
  - Generates byte-for-byte reproducible targets (`SOURCE_DATE_EPOCH` supported, static default timestamp).
- **Engine-Specific Slot Mappings:**
  - `rm2000`: Maps to `CharSet/Actor1.png` with upstream `rtp_table_2k` aliases (`actor1.png`, `Chara1.png`, `chara1.png`, `主人公1.png`). Strictly **excludes** `Hero1.png`.
  - `rm2003`: Maps to `CharSet/Actor1.png` with upstream `rtp_table_2k3` aliases (`actor1.png`, `hero1.png`, `Hero1.png`, `Chara1.png`, `chara1.png`, `protagonist1.png`, `Protagonist1.png`, `主人公1.png`, `주인공1.png`, `主角1.png`).
- **Runtime & Visual Verification:**
  - Executed in EasyRPG Player 0.8.1.1 against distinct clean-room game fixtures ([`tests/fixtures/rm2000_min/`](tests/fixtures/rm2000_min) and [`tests/fixtures/rm2003_min/`](tests/fixtures/rm2003_min)).
  - RM2003 fixture explicitly requests `Hero1` to test the engine-specific alias boundary.
  - Replayed deterministic turning input across all 4 directions with verified clean logs.
  - Directional runtime states visually inspected and verified in:
    - [`artifacts/runtime/rm2000/charset/`](artifacts/runtime/rm2000/charset/) (`rm2000_charset_down.png`, `left`, `up`, `right`, and `negative_control.png`)
    - [`artifacts/runtime/rm2003/charset/`](artifacts/runtime/rm2003/charset/) (`rm2003_charset_down.png`, `left`, `up`, `right`, and `negative_control.png`)
  - Isolated negative controls verified (`Image not found: CharSet/Actor1` for RM2000; `Image not found: CharSet/Hero1` for RM2003).

### 2. ChipSet Fixed-Tile & Layer Composition Slice
- **Single Canonical Asset:** `test.calibration.map-chipset`
  - Neutral 32-bit RGBA source ([`registry/assets/test_calibration_map_chipset.rgba`](registry/assets/test_calibration_map_chipset.rgba)) and preview ([`test_calibration_map_chipset.master.png`](registry/assets/test_calibration_map_chipset.master.png)).
  - 100% synthetic geometric primitives (Blocks E & F fixed tiles).
  - Autotiles (Blocks A–D): Clearly labeled clean-room placeholder tiles; autotile animation and multi-subtile reconstruction are outside the scope of this slice.
- **Physical ChipSet Geometry & Tile Mapping:**
  - Standard 2k-family layout: 480×256 pixels, 30 columns × 16 rows of 16×16 tile units.
  - Fixed-tile bank coordinates mathematically aligned with EasyRPG Player upstream source (`tilemap_layer.cpp`):
    - **Block E Bank 1 (Lower Layer)**: Tile 5000 at col 12, row 0 (blue background, cyan border, yellow center).
    - **Block E Bank 2 (Lower Layer)**: Tile 5096 at col 18, row 0 (green background, lime border, magenta center).
    - **Block F Bank 2 (Upper Layer)**: Tile 10048 at col 24, row 0 (orange diamond on transparent background).
    - **Block F Bank 1 (Upper Layer)**: Tile 10000 at col 18, row 8 (opaque red cross on transparent background).
- **Engine-Specific Slot Mappings:**
  - `rm2000`: `ChipSet/World.png` with aliases `world`, `basis`, `基本`. Emits `Basis.png`. Strictly **excludes** `Main.png` and `Basic.png`.
  - `rm2003`: `ChipSet/World.png` with aliases `world`, `main`, `basic`, `기본`, `基本`. Emits `Main.png` and `Basic.png`. Strictly **excludes** `Basis.png`.
- **Runtime, Layer Transparency & Composition Verification:**
  - Dedicated clean-room fixtures ([`tests/fixtures/rm2000_chipset_min/`](tests/fixtures/rm2000_chipset_min/) and [`tests/fixtures/rm2003_chipset_min/`](tests/fixtures/rm2003_chipset_min/)).
  - Fixtures place party at (0, 0) and position test tiles at (2, 2), (4, 2), (6, 2), and (8, 2).
  - Position (8, 2) composites upper-layer Tile 10000 over lower-layer Tile 5000. Through the transparent corners of the upper red cross, the lower tile's blue background and cyan border are rendered and verified.
  - Positive controls verify clean resolution via RTP alias `Basis` (RM2000) and `Main` (RM2003).
  - Negative controls isolate missing asset detection (`Image not found: ChipSet/Basis` for RM2000; `Image not found: ChipSet/Main` for RM2003).
  - Screenshots inspected and verified under [`artifacts/runtime/rm2000/chipset/`](artifacts/runtime/rm2000/chipset/) and [`artifacts/runtime/rm2003/chipset/`](artifacts/runtime/rm2003/chipset/).

## Repository Layout

```
├── .agents/          # Workspace verification skills
├── artifacts/
│   └── runtime/      # Verified real runtime screenshots and logs (CharSet & ChipSet)
├── docs/             # Technical architecture and research specifications
├── generated/        # Built runtime packages (gitignored)
├── legal/            # Legal documentation and clean-room policies
├── registry/
│   ├── assets/       # Canonical source assets (raw RGBA + metadata)
│   ├── provenance/   # Clean-room provenance sidecars and attestations
│   └── slots/        # Target engine slot mappings
├── schemas/          # JSON schemas for assets, provenance, and slots
├── tests/
│   ├── fixtures/     # Clean-room game fixtures and fixture manifests
│   └── test_vertical_slice.py # Automated test suite
└── tools/            # Generators, target builders, validators, and runtime verifiers
```

## Verification & Build Commands

### 1. Run Automated Test Suite
```bash
SUPERRTP_REQUIRE_RUNTIME=1 python3 tests/test_vertical_slice.py
```
Executes 23 mechanical checks:
1. Canonical master RGBA and preview deterministic reproducibility (CharSet)
2. Target PNG structural compliance (288×256, 8-bit indexed, color type 3, index 0 transparent)
3. Provenance schema completeness and clean-room attestations
4. Target builder byte-for-byte reproducibility across clean runs and RM2000 slot accuracy
5. Validator aggressive rejection of corrupted / invalid assets
6. JSON schema validation on all registry metadata
7. RM2000 clean-room fixture binary and source hash integrity against `fixture_manifest.json`
8. Headless EasyRPG Player RM2000 positive control (clean resolution without missing asset warnings)
9. Headless EasyRPG Player RM2000 negative control (isolated `Image not found: CharSet/Actor1` failure)
10. RM2000 evidence chain cryptographic integrity and 4-direction runtime verification screenshots
11. RM2000 sprite arrow shape orientation and directional asymmetry verification
12. RM2003 target builder, cross-target byte determinism with RM2000, and Hero1 alias inclusion
13. RM2003 clean-room test fixture manifest & programmatic graphics integrity
14. Real EasyRPG Player headless RM2003 RTP resolution (positive control, clean logs)
15. Real EasyRPG Player headless RM2003 missing-asset fallback (negative control, exact failure isolation)
16. RM2003 four-direction runtime verification evidence chain & directional arrow assertions
17. ChipSet canonical asset reproducibility, schemas, and engine-specific slot mappings (RM2000 Basis vs RM2003 Main/Basic)
18. ChipSet multi-category target builder, manifest semantic category presence, category mismatch rejection, and cross-target byte determinism
19. RM2000 and RM2003 clean-room ChipSet fixture manifests, dynamic LCF regeneration, and bundled graphics
20. Real EasyRPG Player RM2000 ChipSet positive control (Basis) and negative control (`Image not found: ChipSet/Basis`)
21. Real EasyRPG Player RM2003 ChipSet positive control (Main) and negative control (`Image not found: ChipSet/Main`)
22. Durable ChipSet runtime verification evidence chain, hashes, and upper/lower layer transparency composition
23. Adversarial evidence-tamper rejection verifying all bound inputs (canonical source, target World.png, manifests, logs, diagnostics, screenshots, engine modes, slots, EasyRPG version)

### 2. Generate Clean-Room Fixture Graphics
```bash
python3 tools/generate_fixture_graphics.py
```
Deterministically generates fallback `ChipSet.png`, `System.png`, and `CharSet/Actor1.png` / `Hero1.png` for test fixtures from geometric primitives using pure Python standard library.

### 3. Generate Canonical Assets
```bash
python3 tools/generate_calibration_charset.py
python3 tools/generate_calibration_chipset.py
```

### 4. Build Target Packs (RM2000 & RM2003)
```bash
python3 tools/build_target.py --target rm2000 --clean
python3 tools/build_target.py --target rm2003 --clean
```

### 5. Validate Target Packs
```bash
python3 tools/validate_target.py --target rm2000
python3 tools/validate_target.py --target rm2003
```

### 6. Runtime Verification & Evidence Verification (EasyRPG Player)
```bash
# Verify existing evidence chains, screenshot hashes, and logs for CharSet:
python3 tools/verify_runtime.py --target all --verify

# Verify existing evidence chains, screenshot hashes, and layer composition for ChipSet:
python3 tools/verify_chipset_runtime.py --target all --verify

# Re-run live replay / capture under virtual X11:
python3 tools/verify_runtime.py --target all --run-replay
python3 tools/verify_chipset_runtime.py --target all --run-capture
```
Generates [`artifacts/runtime/rm2000/charset/verification_evidence.json`](artifacts/runtime/rm2000/charset/verification_evidence.json) and [`artifacts/runtime/rm2003/charset/verification_evidence.json`](artifacts/runtime/rm2003/charset/verification_evidence.json) cryptographically binding engine version, target manifest hash, fixture manifest hash, replay file hash, and screenshot hashes.

## Clean-Room Policy & Licensing

- Code, build tooling, validators, and schemas are licensed under the **MIT License** ([`LICENSE`](LICENSE)).
- Test calibration assets are dedicated to the public domain under **CC0-1.0 Universal**.
- See [legal/CLEAN_ROOM_POLICY.md](legal/CLEAN_ROOM_POLICY.md) for strict contributor clean-room invariants.
