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

## Current Status: Phase 1, 2, 3, 4 & 5 Cross-Target Vertical Slices (Hardened)

The compatibility slices are implemented, hardened, and verified for **cross-target compatibility** across **RPG Maker 2000 (`rm2000`)**, **RPG Maker 2003 (`rm2003`)**, **RPG Maker XP (`rmxp`)**, and **RPG Maker VX (`rmvx`)** from shared canonical source assets:

### 1. CharSet Walking Character Compatibility Slice (Tasks 1 & 2)
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

### 2. ChipSet Fixed-Tile & Layer Composition Slice (Task 3)
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

### 3. RPG Maker XP (RGSS1) Character Compatibility Slice (Task 4)
- **Shared Canonical Source:** Reuses the exact same canonical `test.calibration.walking-character` raw source (SHA-256: `78ad9a170ac0ba06eb4756f9c9c19923e754e82c22025dab7dfbc46de5c1b790`).
- **RGSS1 Character Layout & Geometry:**
  - Extracts Character 0 (top-left 72×128 region, 24×32 frames).
  - Remaps 4 directional rows from RM2k order (`UP`, `RIGHT`, `DOWN`, `LEFT`) to RGSS1 order:
    - **Row 0**: Facing **Down** (`v`)
    - **Row 1**: Facing **Left** (`<`)
    - **Row 2**: Facing **Right** (`>`)
    - **Row 3**: Facing **Up** (`^`)
  - Adapts 3 animation phases (`STEP_LEFT`, `IDLE`, `STEP_RIGHT`) into standard 4-column XP layout:
    - **Column 0**: Step Left
    - **Column 1**: Idle / Standing
    - **Column 2**: Step Right
    - **Column 3**: Idle / Standing (duplicated from Column 1)
  - Output sheet dimensions: **96×128** pixels.
- **Deterministic 32-bit Truecolor RGBA Encoder:**
  - Encodes directly into 32-bit truecolor RGBA PNG (Color Type 6, bit depth 8) using RFC 1951 stored blocks for bit-level determinism across platforms.
  - Strictly omits `PLTE` chunk and preserves full alpha channel ($0 \le \alpha \le 255$).
- **Target Slot Mapping:**
  - `rmxp`: Emits `Graphics/Characters/001-Fighter01.png` (SHA-256: `b4e81694247632b5580b5eef55a17e61c6afd709092de0e574aed70b41759743`).
- **Runtime & Visual Verification (mkxp-z):**
  - Executed using pinned `mkxp-z` (commit `826929eeb3ebc4b887c011604919217a790770f4`) with clean-room RGSS1 test harness ([`tests/fixtures/rmxp_character_min/`](tests/fixtures/rmxp_character_min/)).
  - Positive control: Renders 96×128 sprite over a centered high-contrast test pad (260, 164, 120×152) with distinct corner alignment markers (Red TL, Green TR, Blue BL, Yellow BR).
  - Deterministic pixel assertions verify directional arrow tips and transparency notches exposing underlying pad color across all 4 rows.
  - Negative control: With empty RTP, `Bitmap.new` raises `Errno::ENOENT`, logged as `SUPERRTP_RMXP_MISSING_ASSET: No such file or directory - Graphics/Characters/001-Fighter01` with clean non-zero exit (exit code 1). Negative screenshot captures blank pad with no sprite rendered.
  - Durable evidence recorded and verified in [`artifacts/runtime/rmxp/character/verification_evidence.json`](artifacts/runtime/rmxp/character/verification_evidence.json).

### 4. RPG Maker VX (RGSS2) Standard 8-Character Compatibility Slice (Task 5)
- **Shared Canonical Source:** Reuses the exact same canonical `test.calibration.walking-character` raw source (SHA-256: `78ad9a170ac0ba06eb4756f9c9c19923e754e82c22025dab7dfbc46de5c1b790`).
- **Standard 8-Character Sheet Geometry & Direction Rows:**
### 4. RPG Maker VX (RGSS2) Standard 8-Character Slice (Task 5)
- **Standard 8-Character Sheet Packing:**
  - Extracts all 8 characters ($0..7$) semantically via `extract_walking_frames()`.
  - Packs characters in a $4 \times 2$ grid ($288 \times 256$ pixels), strictly preserving character indices without permutation.
  - Each character is $72 \times 128$ pixels, comprising $3 \times 4$ cells of $24 \times 32$ pixels (96 cells total).
  - Remaps 4 directional rows to RGSS2 standard order:
    - **Row 0**: Facing **Down** (`v`)
    - **Row 1**: Facing **Left** (`<`)
    - **Row 2**: Facing **Right** (`>`)
    - **Row 3**: Facing **Up** (`^`)
  - Three animation columns per character:
    - **Column 0**: Step Left
    - **Column 1**: Idle / Standing
    - **Column 2**: Step Right
- **Clean-Room Boundary & Scope Invariant:**
  - Zero proprietary RPG Maker VX RTP creative content. The official `Actor1.png` pixels were never downloaded, viewed, or traced.
  - Prefix behaviors (`$` for single-character sheets, `!` for disabling the 4-pixel shift and bush transparency depth) are documented as unverified and are not implemented in this slice.
- **Deterministic 32-bit Truecolor RGBA Encoder:**
  - Encodes directly into 32-bit truecolor RGBA PNG (Color Type 6, bit depth 8) with RFC 1951 stored blocks for deterministic byte output across platforms.
- **Target Slot Mapping:**
  - `rmvx`: Emits `Graphics/Characters/Actor1.png` (SHA-256: `c6ed8cba9025b982c6300ed5e57a82aee99cc29f7929d81cf1b517ded47550bf`). Slot provenance documented from Steam Depot 521881.
- **Runtime & Visual Verification (mkxp-z in RGSS2 mode):**
  - Executed using pinned `mkxp-z` (commit `826929eeb3ebc4b887c011604919217a790770f4`) in RGSS2 mode (`rgssVersion: 2`, screen resolution $544 \times 416$) against clean-room test harness ([`tests/fixtures/rmvx_character_min/`](tests/fixtures/rmvx_character_min/)).
  - Positive control: Renders $288 \times 256$ sheet centered at $(128, 80)$ over high-contrast test pad $(116, 68, 312 \times 280)$ with 4 distinct corner alignment markers. Verified 100% pixel composite match across the $288 \times 256$ region against underlying pad, verified all 8 character block placements, and verified directional arrow orientations and transparency notches.
  - Negative control: With empty RTP, `Bitmap.new` raises `Errno::ENOENT`, logged as `SUPERRTP_RMVX_MISSING_ASSET: No such file or directory - Graphics/Characters/Actor1` with clean non-zero exit (exit code 1). Negative screenshot captures blank pad with no sprite rendered.
  - Durable evidence recorded and verified in [`artifacts/runtime/rmvx/character/verification_evidence.json`](artifacts/runtime/rmvx/character/verification_evidence.json).

### 5. RPG Maker VX Ace (RGSS3) Standard 8-Character Slice (Task 6)
- **Engine-Identity Separation with Shared Physical Geometry:**
  - Proves that RPG Maker VX (`rmvx`, RGSS2) and RPG Maker VX Ace (`rmvxace`, RGSS3) share identical physical 8-character sheet layout ($288 \times 256$ RGBA PNG, $4 \times 2$ grid, 3 animation columns $\times$ 4 direction rows) while maintaining strictly separated target identities, manifests, transform policies, and runtime proofs.
  - Core physical layout is packaged once via `pack_vx_family_standard_character_sheet()`, avoiding code duplication or speculative class hierarchies.
- **Byte-for-Byte Payload Equality:**
  - `generated/rmvx/Graphics/Characters/Actor1.png` and `generated/rmvxace/Graphics/Characters/Actor1.png` are byte-identical (SHA-256: `c6ed8cba9025b982c6300ed5e57a82aee99cc29f7929d81cf1b517ded47550bf`).
- **Separate Target Contracts & Metadata:**
  - `rmvx`: target `rmvx`, engine `RPG Maker VX`, mode `rgss2`, policy `rm2k8_to_rgss2_standard_character_sheet_v1`.
  - `rmvxace`: target `rmvxace`, engine `RPG Maker VX Ace`, mode `rgss3`, policy `rm2k8_to_rgss3_standard_character_sheet_v1`.
  - Manifest and registry cross-validation enforces target, category, indices, and policy integrity.
- **Runtime & Visual Verification (mkxp-z in RGSS3 mode):**
  - Executed using pinned `mkxp-z` in RGSS3 mode (`rgssVersion: 3`, screen resolution $544 \times 416$) against clean-room test harness ([`tests/fixtures/rmvxace_character_min/`](tests/fixtures/rmvxace_character_min/)).
  - Startup verified via explicit mkxp-z startup log: `RGSS version 3 (RPG Maker VX Ace) `.
  - Positive control renders $288 \times 256$ sheet centered at $(128, 80)$ on pad; 100% composite match and alpha transparency verified.
  - Negative control isolates missing asset with deterministic diagnostic `SUPERRTP_RMVXACE_MISSING_ASSET: No such file or directory - Graphics/Characters/Actor1` and exit code 1.
  - Durable evidence recorded and verified in [`artifacts/runtime/rmvxace/character/verification_evidence.json`](artifacts/runtime/rmvxace/character/verification_evidence.json).

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

### 1. Run Automated Test Suites
```bash
# Tasks 1–3: RM2000 & RM2003 CharSet and ChipSet test suite (23 tests)
SUPERRTP_REQUIRE_RUNTIME=1 python3 tests/test_vertical_slice.py

# Task 4: RPG Maker XP / RGSS1 Character test suite (12 tests)
SUPERRTP_REQUIRE_RUNTIME=1 python3 tests/test_rmxp_vertical_slice.py

# Task 5: RPG Maker VX / RGSS2 Character test suite (14 tests)
SUPERRTP_REQUIRE_RUNTIME=1 python3 tests/test_rmvx_vertical_slice.py

# Task 6: RPG Maker VX Ace / RGSS3 Character test suite (15 tests)
SUPERRTP_REQUIRE_RUNTIME=1 python3 tests/test_rmvxace_vertical_slice.py
```
Executes 64 mechanical checks across all targets:
- **Tasks 1–3 Suite (23 tests)**: Canonical master RGBA/PNG reproducibility, 8-bit indexed format compliance, provenance schemas, deterministic target builder, validator rejections, liblcf fixture generation, headless EasyRPG positive/negative controls, 4-direction turning verification, ChipSet fixed-tile geometry (Blocks E/F), layer transparency composition, and adversarial evidence tamper suites.
- **Task 4 Suite (12 tests)**: Deterministic truecolor RGBA PNG encoding with full alpha range, semantic walking frame extraction, 4×4 RGSS1 packing and direction remapping from canonical sheet, RMXP target build reproducibility, frozen baseline regression integrity across all 3 engines, target validation for RMXP, validator rejections (bad dimensions, paletted PNG, missing alpha, idle column mismatch), clean-room RGSS1 fixture manifest integrity, live headless mkxp-z positive resolution, live headless mkxp-z negative control (`Errno::ENOENT`, exit code 1), complete durable evidence chain verification, and 20+ field adversarial tamper rejection.
- **Task 5 Suite (14 tests)**: Canonical walking character asset integrity, semantic 8-character extraction against independent physical crop oracle, RGSS2 standard $4\times 2$ character sheet packing geometry, 96-cell exact byte equality directly against independent physical source crops, single-frame mutation locality (one cell mutation alters only that target cell and leaves all 95 others 100% byte-identical), character index preservation and non-scrambling test, adversarial packer validation, RMVX target build reproducibility, frozen baseline regression integrity across all 4 targets, RMVX target validator adversarial rejections (wrong source indices, missing/wrong transform policy, wrong category, wrong target hash, directional-row permutation), live headless mkxp-z RGSS2 positive resolution ($544\times 416$), live headless mkxp-z negative control (`Errno::ENOENT`, exit code 1), complete durable evidence chain verification, and expanded adversarial tamper rejection including build config options, diagnostics, and actual screenshot pixel corruption.
- **Task 6 Suite (15 tests)**: Canonical walking character asset integrity, 8-character semantic extraction against independent physical crop oracle, shared VX-family 8-character packing and thin wrapper verification, 96-cell exact byte equality directly against independent physical crops, single-frame mutation locality (1 frame mutated, 95 cells byte-identical), cross-target byte equality (`rmvx` Actor1 bytes == `rmvxace` Actor1 bytes) alongside distinct engine/target manifests and transform policies, independent build without reading `generated/rmvx`, A/B deterministic build reproducibility, frozen baseline regression integrity across all 5 targets, RMVXAce validator adversarial rejections (wrong category, wrong target SHA, corrupted indices, wrong/missing transform policy, row permutation), clean-room RGSS3 fixture integrity, live headless mkxp-z RGSS3 positive resolution (`RGSS version 3 (RPG Maker VX Ace)` banner, $544\times 416$ screen), live headless mkxp-z negative control (`SUPERRTP_RMVXACE_MISSING_ASSET: Graphics/Characters/Actor1`, exit code 1), complete durable evidence chain verification, and expanded 22+ field adversarial tamper suite including nested build config and screenshot pixel corruption.

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

### 4. Build Target Packs (RM2000, RM2003, RMXP, RMVX & RMVXAce)
```bash
python3 tools/build_target.py --target rm2000 --clean
python3 tools/build_target.py --target rm2003 --clean
python3 tools/build_target.py --target rmxp --clean
python3 tools/build_target.py --target rmvx --clean
python3 tools/build_target.py --target rmvxace --clean
```

### 5. Validate Target Packs
```bash
python3 tools/validate_target.py --target rm2000
python3 tools/validate_target.py --target rm2003
python3 tools/validate_target.py --target rmxp
python3 tools/validate_target.py --target rmvx
python3 tools/validate_target.py --target rmvxace
```

### 6. Runtime Verification & Evidence Verification (EasyRPG Player & mkxp-z)
```bash
# Verify existing evidence chains, screenshot hashes, and logs:
python3 tools/verify_runtime.py --target all --verify
python3 tools/verify_chipset_runtime.py --target all --verify
python3 tools/verify_rmxp_runtime.py --verify
python3 tools/verify_rmvx_runtime.py --verify
python3 tools/verify_rmvxace_runtime.py --verify

# Re-run live replay / capture under virtual X11:
python3 tools/verify_runtime.py --target all --run-replay
python3 tools/verify_chipset_runtime.py --target all --run-capture
python3 tools/verify_rmxp_runtime.py --run-capture
python3 tools/verify_rmvx_runtime.py --run-capture
python3 tools/verify_rmvxace_runtime.py --run-capture
```
Generates and validates cryptographic evidence chains:
- [`artifacts/runtime/rm2000/charset/verification_evidence.json`](artifacts/runtime/rm2000/charset/verification_evidence.json)
- [`artifacts/runtime/rm2003/charset/verification_evidence.json`](artifacts/runtime/rm2003/charset/verification_evidence.json)
- [`artifacts/runtime/rm2000/chipset/verification_evidence.json`](artifacts/runtime/rm2000/chipset/verification_evidence.json)
- [`artifacts/runtime/rm2003/chipset/verification_evidence.json`](artifacts/runtime/rm2003/chipset/verification_evidence.json)
- [`artifacts/runtime/rmxp/character/verification_evidence.json`](artifacts/runtime/rmxp/character/verification_evidence.json)
- [`artifacts/runtime/rmvx/character/verification_evidence.json`](artifacts/runtime/rmvx/character/verification_evidence.json)
- [`artifacts/runtime/rmvxace/character/verification_evidence.json`](artifacts/runtime/rmvxace/character/verification_evidence.json)


## Clean-Room Policy & Licensing

- Code, build tooling, validators, and schemas are licensed under the **MIT License** ([`LICENSE`](LICENSE)).
- Test calibration assets are dedicated to the public domain under **CC0-1.0 Universal**.
- See [legal/CLEAN_ROOM_POLICY.md](legal/CLEAN_ROOM_POLICY.md) for strict contributor clean-room invariants.
