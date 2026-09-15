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
- For CharSet: replays deterministic multi-frame inputs navigating all 4 directional faces, verifying facing arrows.
- For ChipSet: boots new game into 20×15 map with fixed test tiles, capturing 640×480 screenshots with lossless RGB recording (`-c:v libx264rgb -crf 0`).
- Performs mechanical pixel assertions on all key tile regions and layer composition transparency.
- Generates `verification_evidence.json` under `artifacts/runtime/<target>/<category>/`, cryptographically binding canonical source SHA-256, target manifest hash, fixture manifest hash, EasyRPG pinned version (0.8.1.1), log hashes, negative control diagnostics, and screenshot hashes.
- All recorded fields in `verification_evidence.json` are strictly enforced by `--verify` across both `verify_runtime.py` and `verify_chipset_runtime.py`. Automated adversarial tamper tests (`test_23`) deliberately corrupt each bound input and assert immediate rejection.
