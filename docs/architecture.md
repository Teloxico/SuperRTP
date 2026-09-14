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
   - Slot mappings are derived directly from upstream EasyRPG `src/rtp_table.cpp`.
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

## 4. Deterministic Reproducibility

Builds are required to be bit-for-bit reproducible:
- The builder quantizes colors using a deterministic scanline ordering.
- `manifest.json` timestamps support `SOURCE_DATE_EPOCH` environment variables and default to a static ISO epoch (`1970-01-01T00:00:00Z`).
- Automated tests verify that successive clean builds produce identical hashes across all generated files.

## 5. Clean-Room Test Fixtures

Test fixtures under `tests/fixtures/rm2000_min/` are generated from clean-room source code using `liblcf` (`tools/generate_fixture.cpp`).
- Binaries contain zero proprietary assets.
- `tests/fixtures/rm2000_min/fixture_manifest.json` tracks the generator source SHA-256 and binary file hashes.
- Bundled fallback assets (`ChipSet/ChipSet.png`, `System/System.png`) eliminate non-RTP runtime log noise during automated test runs.
