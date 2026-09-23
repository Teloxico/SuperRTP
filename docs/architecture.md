# SuperRTP Architecture

## 1. System Pipeline

SuperRTP maintains **one canonical source of truth** for compatibility and creative assets. Engine-specific RTP packs are deterministic generated artifacts, not independently maintained repositories.

The core pipeline flow is:

```
canonical source (neutral RGBA / metadata)
  │
  ├──> provenance attestation (schemas/provenance.schema.json)
  │
  ├──> semantic identity (registry/assets/<asset-id>.json)
  │
  ├──> compatibility mapping (registry/slots/<target>.json)
  │
  ├──> deterministic transformation (tools/build_target.py)
  │
  ├──> target-specific output (generated/<target>/)
  │
  └──> runtime verification (EasyRPG / mkxp-z / fixtures)
```

## 2. Engine Compatibility Models

Different RPG engine generations employ fundamentally different resource lookup models:

1. **RPG Maker 2000 / 2003 (EasyRPG Player)**:
   - Uses case-insensitive table-based alias lookup.
   - Primary filenames and historical localization aliases differ between versions (e.g., `Actor1` vs `Hero1`, `Chara1`, Japanese `主人公1`).
   - Slot mappings are derived directly from upstream EasyRPG `src/rtp_table.cpp` (table `rtp_table_2k`, release commit `78328fa` / v0.8.1.1).
   - Palette color format: 8-bit indexed PNG (maximum 256 colors).
   - RM2000 transparency model: Palette index 0 is designated as transparent color. SuperRTP additionally provides standard `tRNS` chunks for modern viewer compatibility.

2. **RPG Maker XP / VX / VX Ace (mkxp-z)**:
   - RGSS resource search paths with explicit RTP fallbacks.
   - 32-bit RGBA PNG with alpha channels.

3. **WOLF RPG Editor**:
   - Custom folder hierarchies and internal data references.

## 3. CharSet Physical Geometry & Direction Order

For RPG Maker 2000 / 2003 character spritesheets:
- Total dimensions: **288 x 256** pixels.
- Character grid: **4 columns x 2 rows** (8 characters total, 72 x 128 pixels per character).
- Character frames: **3 columns x 4 rows** (24 x 32 pixels per frame).
- Animation columns:
  - Column 0: Left step
  - Column 1: Idle / standing
  - Column 2: Right step
- **Directional row order** (verified against EasyRPG `game_character.h` enum `Up=0, Right=1, Down=2, Left=3` and `sprite_character.cpp`):
  - **Row 0**: Facing **Up** (`^`)
  - **Row 1**: Facing **Right** (`>`)
  - **Row 2**: Facing **Down** (`v`)
  - **Row 3**: Facing **Left** (`<`)

## 4. ChipSet Physical Geometry, Tile Blocks & Layer Composition

For RPG Maker 2000 / 2003 tilesets:
- Total dimensions: **480 x 256** pixels.
- Tile grid: **30 columns x 16 rows** of 16 x 16 pixel tile units.
- Block breakdown (verified against EasyRPG upstream `src/map_data.h` and `src/tilemap_layer.cpp`):
  - **Blocks A–D (Cols 0..11)**: Autotile banks (animated water, shores, structures). Clean-room placeholder tiles in Phase 3; multi-subtile autotile reconstruction is outside the scope of fixed-tile testing.
  - **Block E Bank 1 (Cols 12..17, Rows 0..15)**: Lower-layer fixed tiles (IDs 5000..5095).
    - Tile 5000 (`col = 12 + id % 6, row = id / 6` -> col 12, row 0): blue background `(12, 48, 160)`, cyan border `(0, 240, 255)`, yellow center `(255, 220, 30)`.
  - **Block E Bank 2 (Cols 18..23, Rows 0..7)**: Lower-layer fixed tiles (IDs 5096..5143).
    - Tile 5096 (`col = 18 + (id - 96) % 6, row = (id - 96) / 6` -> col 18, row 0): green background `(15, 120, 45)`, lime border `(50, 255, 80)`, magenta center `(250, 40, 200)`.
  - **Block F Bank 1 (Cols 18..23, Rows 8..15)**: Upper-layer fixed tiles (IDs 10000..10047).
    - Tile 10000 (`col = 18 + id % 6, row = 8 + id / 6` -> col 18, row 8): opaque red cross `(230, 30, 30)` on 100% transparent background (index 0).
  - **Block F Bank 2 (Cols 24..29, Rows 0..15)**: Upper-layer fixed tiles (IDs 10048..10143).
    - Tile 10048 (`col = 24 + (id - 48) % 6, row = (id - 48) / 6` -> col 24, row 0): opaque orange diamond `(255, 130, 10)` on 100% transparent background.
- **Layer Composition & Transparency Verification**:
  - Upper layer tiles (Block F) render over lower layer tiles (Block E / Block A).
  - Placing Tile 10000 on upper layer over Tile 5000 on lower layer results in:
    - Center pixels display upper layer red cross `(230, 30, 30)`.
    - Corner pixels display lower layer cyan border `(0, 240, 255)` and blue background `(12, 48, 160)` through the transparent upper layer.

## 5. Deterministic Reproducibility

Builds are required to be bit-for-bit reproducible:
- The builder performs deterministic exact palette extraction and indexing (requiring $\le 256$ unique colors, sorted by RGBA appearance).
- `manifest.json` timestamps support `SOURCE_DATE_EPOCH` environment variables and default to a static ISO epoch (`1970-01-01T00:00:00Z`).
- Automated tests verify that successive clean builds produce identical hashes across all generated files.

## 6. Clean-Room Test Fixtures

Test fixtures under `tests/fixtures/` (`rm2000_min`, `rm2003_min`, `rm2000_chipset_min`, `rm2003_chipset_min`) are generated entirely from clean-room source code:
- Map and database binaries (`LMT`, `LDB`, `LMU`) are generated via `liblcf` (`tools/generate_fixture.cpp`).
- Minimal fallback graphics (`ChipSet.png`, `System.png`, `CharSet/Actor1.png`) are generated deterministically using pure Python standard library (`tools/generate_fixture_graphics.py`) from geometric shapes.
- Binaries and graphics contain zero proprietary creative assets.
- `fixture_manifest.json` in each fixture tracks generator source SHA-256 and binary/graphic file hashes.
- In CharSet fixtures (`*_min/`), zero CharSets are bundled, isolating CharSet RTP resolution.
- In ChipSet fixtures (`*_chipset_min/`), zero ChipSets are bundled, isolating ChipSet RTP resolution (`Basis` in RM2000, `Main` in RM2003).

## 7. Runtime Verification & Evidence Chaining

Runtime verification is executed through `tools/verify_runtime.py` and `tools/verify_chipset_runtime.py`:
- Drives headless EasyRPG Player via an Xvfb virtual frame buffer.
- For CharSet: turns the hero through all 4 directions with X11 key presses, capturing each facing once the screen shows it and checking its arrow shape and position.
- For ChipSet: boots new game into 20×15 map with fixed test tiles, capturing 640×480 screenshots with lossless RGB recording (`-c:v libx264rgb -crf 0`).
- Performs mechanical pixel assertions on all key tile regions and layer composition transparency.
- Generates `verification_evidence.json` under `artifacts/runtime/<target>/<category>/`, cryptographically binding canonical source SHA-256, target manifest hash, fixture manifest hash, EasyRPG pinned version (0.8.1.1), log hashes, negative control diagnostics, and screenshot hashes.
- All recorded fields in `verification_evidence.json` are strictly enforced by `--verify` across both `verify_runtime.py` and `verify_chipset_runtime.py`. `tests/test_runtime_evidence.py` mutates or removes every field of every evidence file and requires rejection.

Shared runtime code lives in `tools/runtime_harness.py` (Xvfb via `-displayfd`, lossless recording, frame selection by content, key presses, screen polling) with per-engine drivers `tools/easyrpg_runtime.py`, `tools/mkxp_runtime.py` and `tools/wolf_runtime.py`. Researched engine behavior is recorded in [engine-facts.md](engine-facts.md).

## 8. RPG Maker XP (RGSS1) Character Architecture

SuperRTP's single-source architecture enables generating RGSS1-compliant character sheets directly from the canonical walking-character source:

1. **Extraction & Spatial Remapping:**
   - Canonical walking-character sheet is 288×256 pixels containing 8 characters (4×2 grid of 72×128 px).
   - Character 0 (top-left 72×128 px) is extracted, consisting of 3 columns × 4 rows of 24×32 frames.
   - **Direction Row Remapping:**
     - RM2000 physical rows: Row 0 (UP), Row 1 (RIGHT), Row 2 (DOWN), Row 3 (LEFT).
     - RGSS1 physical rows: Row 0 (DOWN), Row 1 (LEFT), Row 2 (RIGHT), Row 3 (UP).
   - **Animation Column Adaptation:**
     - RM2000 uses 3 frame columns: Step Left (Col 0), Idle (Col 1), Step Right (Col 2).
     - RGSS1 stands on column 0 and walks through columns 0, 1, 2, 3 (`Game_Character#@original_pattern = 0`; `Sprite_Character` uses `sx = pattern * width / 4`). The idle frame must therefore be in column 0.
     - Output columns: Idle (Col 0), Step Right (Col 1), Idle (Col 2), Step Left (Col 3), giving a 96×128 pixel sheet (4 cols × 24 px, 4 rows × 32 px). Policy `rm2k_to_rgss1_character_4x4_idle_first_v2` (the v1 policy put a stepping frame in column 0).

2. **Deterministic Truecolor RGBA Encoding (Color Type 6):**
   - RPG Maker XP and mkxp-z use full 32-bit RGBA PNGs rather than indexed palettes.
   - `tools/png_utils.py` provides `create_rgba_png(width, height, rgba_bytes)`:
     - Formats standard PNG chunks: `IHDR` (Color Type 6, bit depth 8, dimensions 96×128), `IDAT`, `IEND`.
     - Strictly omits `PLTE` (palette) chunks.
     - Compresses raw scanlines (with filter type 0 / None) using RFC 1951 uncompressed stored blocks via `deterministic_zlib_compress`. This guarantees byte-for-byte identical output regardless of system zlib implementation or platform differences.
     - Preserves full alpha range ($0 \le \alpha \le 255$) without pre-multiplication.

3. **Clean-Room RGSS1 Test Harness & mkxp-z Runtime Oracle:**
   - Pinned runner: `mkxp-z` built from commit `826929eeb3ebc4b887c011604919217a790770f4` with `-Dworkdir_current=true`.
   - Test fixture under `tests/fixtures/rmxp_character_min/`:
     - `fixture.rb`: Clean-room Ruby script setting up a 640×480 scene with neutral dark background `(25, 25, 30)` and a high-contrast test pad `(210, 215, 220)` at `(260, 164, 120×152)` with distinct corner alignment markers (Red TL, Green TR, Blue BL, Yellow BR).
     - Loads `Bitmap.new("Graphics/Characters/001-Fighter01")` and displays the full 96×128 character sheet at `(272, 176)`.
     - Positive control: Renders 60 frames and exits with code 0.
     - Negative control: When RTP is empty, catches `Errno::ENOENT`, logs `SUPERRTP_RMXP_MISSING_ASSET: No such file or directory - Graphics/Characters/001-Fighter01`, renders 30 frames of the blank pad, and exits with code 1.
   - Evidence recorded in `artifacts/runtime/rmxp/character/verification_evidence.json` binding commit `826929e`, target manifest hash, target character hash, fixture manifest hash, logs, diagnostics, and screenshots.

## 9. RPG Maker VX (RGSS2) Character Architecture

SuperRTP's semantic walking-frame abstraction enables feeding RPG Maker VX's standard 8-character sheet directly from the same canonical walking-character source:

1. **Semantic Extraction & 8-Character Standard Sheet Packing:**
   - Canonical walking-character source contains 8 characters (4×2 grid of 72×128 px, 24×32 frames).
   - `extract_walking_frames()` extracts pure semantic representations (`UP/RIGHT/DOWN/LEFT` × `STEP_LEFT/IDLE/STEP_RIGHT`) for all eight characters ($0..7$).
   - `pack_rmvx_character_sheet()` arranges the 8 characters into a standard 4×2 grid ($288\times 256$ pixels):
     - Characters 0..3 on top row ($y=0..127$).
     - Characters 4..7 on bottom row ($y=128..255$).
   - **Direction Row Ordering:**
     - Row 0: Facing **Down** (`v`)
     - Row 1: Facing **Left** (`<`)
     - Row 2: Facing **Right** (`>`)
     - Row 3: Facing **Up** (`^`)
   - **Animation Column Mapping:**
     - Column 0: Step Left (`STEP_LEFT`)
     - Column 1: Idle / Standing (`IDLE`)
     - Column 2: Step Right (`STEP_RIGHT`)
   - Unlike XP, no fourth repeated idle column is added; VX standard sheets natively use 3 animation patterns.

2. **Architectural Distinction Between XP and VX:**
   - **XP / RGSS1**: One character per file for Task 4, 4 animation columns (`IDLE`, `STEP_RIGHT`, `IDLE`, `STEP_LEFT`), 96×128 pixels, 640×480 screen.
   - **VX / RGSS2**: Standard 8-character sheet, 3 animation columns (`STEP_LEFT`, `IDLE`, `STEP_RIGHT`), 288×256 pixels, 544×416 screen.
   - Documented `$` (single character) and `!` (no offset / bush translucency) filename prefixes are recognized functional facts of the engine but are intentionally outside the scope of Task 5 and remain unverified.
   - RPG Maker VX Ace (`rmvxace`) is a separate engine target (RGSS3) and is not implemented in Task 5.

3. **Clean-Room RGSS2 Test Harness & Runtime Verification:**
   - Pinned runner: `mkxp-z` built from commit `826929eeb3ebc4b887c011604919217a790770f4` with `rgssVersion = 2`.
   - Test fixture under `tests/fixtures/rmvx_character_min/`:
     - `fixture.rb`: Clean-room Ruby script asserting screen dimensions $544\times 416$ (`SUPERRTP_RGSS2_SCREEN 544x416`), setting up a test pad `(210, 215, 220)` at `(116, 68, 312×280)` with 4 corner alignment markers (Red TL, Green TR, Blue BL, Yellow BR).
     - Loads `Bitmap.new("Graphics/Characters/Actor1")` (omitted `.png` extension) via RGSS2 RTP resolution.
     - Positions the full 288×256 sheet at `(128, 80)` (centered in 544×416).
     - Positive control: Renders 60 frames and exits with code 0.
     - Negative control: With empty RTP, catches `Errno::ENOENT`, logs `SUPERRTP_RMVX_MISSING_ASSET: No such file or directory - Graphics/Characters/Actor1`, renders 30 frames of the blank pad, and exits with code 1.
   - Evidence recorded in `artifacts/runtime/rmvx/character/verification_evidence.json` binding commit `826929e`, target manifest hash, target character hash, fixture manifest hash, logs, diagnostics, and screenshots.

## 10. Informational Derived Summary Documentation

Any derived summaries, test reports, walkthroughs, or compatibility documentation generated during development are strictly informational and secondary to:
1. Canonical source assets (`registry/assets/`) and provenance records (`registry/provenance/`).
2. Target slot registries (`registry/slots/`) and schemas (`schemas/`).
3. Deterministic code, tests, and build tooling (`tools/`, `tests/`).
4. Real runtime execution evidence and inspected screenshot artifacts (`artifacts/runtime/`).


