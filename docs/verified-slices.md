# Verified Compatibility Slices

Detailed specification of each vertical slice: canonical source, target geometry, slot
mapping, and the runtime evidence that proves it. The [README](../README.md) has the
overview; [architecture.md](architecture.md) has the design and
[engine-facts.md](engine-facts.md) has the researched engine behavior these slices
rely on.

## 1. CharSet Walking Character Compatibility Slice (Tasks 1 & 2)
- **Single Canonical Asset:** `test.calibration.walking-character`
  - Neutral 32-bit RGBA source ([`registry/assets/test_calibration_walking_character.rgba`](../registry/assets/test_calibration_walking_character.rgba)) and preview ([`test_calibration_walking_character_master.png`](../registry/assets/test_calibration_walking_character_master.png)).
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
  - Executed in EasyRPG Player 0.8.1.1 against distinct clean-room game fixtures ([`tests/fixtures/rm2000_min/`](../tests/fixtures/rm2000_min) and [`tests/fixtures/rm2003_min/`](../tests/fixtures/rm2003_min)).
  - RM2003 fixture explicitly requests `Hero1` to test the engine-specific alias boundary.
  - The hero is turned through all 4 directions with real X11 key presses (xdotool); each facing is captured once the screen shows it. EasyRPG's `--replay-input` is not used because its reader applies an input only on an exact frame match ([docs/engine-facts.md](engine-facts.md)).
  - Live re-capture is intermittent on this slice; see [docs/known-issues.md](known-issues.md). The committed evidence verifies.
  - Directional runtime states visually inspected and verified in:
    - [`artifacts/runtime/rm2000/charset/`](../artifacts/runtime/rm2000/charset/) (`rm2000_charset_down.png`, `left`, `up`, `right`, and `negative_control.png`)
    - [`artifacts/runtime/rm2003/charset/`](../artifacts/runtime/rm2003/charset/) (`rm2003_charset_down.png`, `left`, `up`, `right`, and `negative_control.png`)
  - Isolated negative controls verified (`Image not found: CharSet/Actor1` for RM2000; `Image not found: CharSet/Hero1` for RM2003).

## 2. ChipSet Fixed-Tile & Layer Composition Slice (Task 3)
- **Single Canonical Asset:** `test.calibration.map-chipset`
  - Neutral 32-bit RGBA source ([`registry/assets/test_calibration_map_chipset.rgba`](../registry/assets/test_calibration_map_chipset.rgba)) and preview ([`test_calibration_map_chipset.master.png`](../registry/assets/test_calibration_map_chipset.master.png)).
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
  - Dedicated clean-room fixtures ([`tests/fixtures/rm2000_chipset_min/`](../tests/fixtures/rm2000_chipset_min/) and [`tests/fixtures/rm2003_chipset_min/`](../tests/fixtures/rm2003_chipset_min/)).
  - Fixtures place party at (0, 0) and position test tiles at (2, 2), (4, 2), (6, 2), and (8, 2).
  - Position (8, 2) composites upper-layer Tile 10000 over lower-layer Tile 5000. Through the transparent corners of the upper red cross, the lower tile's blue background and cyan border are rendered and verified.
  - Positive controls verify clean resolution via RTP alias `Basis` (RM2000) and `Main` (RM2003).
  - Negative controls isolate missing asset detection (`Image not found: ChipSet/Basis` for RM2000; `Image not found: ChipSet/Main` for RM2003).
  - Screenshots inspected and verified under [`artifacts/runtime/rm2000/chipset/`](../artifacts/runtime/rm2000/chipset/) and [`artifacts/runtime/rm2003/chipset/`](../artifacts/runtime/rm2003/chipset/).

## 3. RPG Maker XP (RGSS1) Character Compatibility Slice (Task 4)
- **Shared Canonical Source:** Reuses the exact same canonical `test.calibration.walking-character` raw source (SHA-256: `78ad9a170ac0ba06eb4756f9c9c19923e754e82c22025dab7dfbc46de5c1b790`).
- **RGSS1 Character Layout & Geometry:**
  - Extracts Character 0 (top-left 72×128 region, 24×32 frames).
  - Remaps 4 directional rows from RM2k order (`UP`, `RIGHT`, `DOWN`, `LEFT`) to RGSS1 order:
    - **Row 0**: Facing **Down** (`v`)
    - **Row 1**: Facing **Left** (`<`)
    - **Row 2**: Facing **Right** (`>`)
    - **Row 3**: Facing **Up** (`^`)
  - Adapts 3 animation phases (`STEP_LEFT`, `IDLE`, `STEP_RIGHT`) into the 4-column XP layout. RGSS1 draws a standing character from column 0 and walks through columns 0-3 (`@original_pattern = 0`, `sx = pattern * width / 4`; see [docs/engine-facts.md](engine-facts.md)), so the idle frame comes first:
    - **Column 0**: Idle / Standing
    - **Column 1**: Step Right
    - **Column 2**: Idle / Standing
    - **Column 3**: Step Left
  - Policy: `rm2k_to_rgss1_character_4x4_idle_first_v2`.
  - Output sheet dimensions: **96×128** pixels.
- **Deterministic 32-bit Truecolor RGBA Encoder:**
  - Encodes directly into 32-bit truecolor RGBA PNG (Color Type 6, bit depth 8) using RFC 1951 stored blocks for bit-level determinism across platforms.
  - Strictly omits `PLTE` chunk and preserves full alpha channel ($0 \le \alpha \le 255$).
- **Target Slot Mapping:**
  - `rmxp`: Emits `Graphics/Characters/001-Fighter01.png` (SHA-256: `fbd8e9705577b6c14420fa37b63b1cda0888e7488a80123aa1ae14aac236e6dd`).
- **Runtime & Visual Verification (mkxp-z):**
  - Executed using pinned `mkxp-z` (commit `826929eeb3ebc4b887c011604919217a790770f4`) with clean-room RGSS1 test harness ([`tests/fixtures/rmxp_character_min/`](../tests/fixtures/rmxp_character_min/)).
  - Positive control: Renders 96×128 sprite over a centered high-contrast test pad (260, 164, 120×152) with distinct corner alignment markers (Red TL, Green TR, Blue BL, Yellow BR).
  - Deterministic pixel assertions verify directional arrow tips and transparency notches exposing underlying pad color across all 4 rows.
  - Negative control: With empty RTP, `Bitmap.new` raises `Errno::ENOENT`, logged as `SUPERRTP_RMXP_MISSING_ASSET: No such file or directory - Graphics/Characters/001-Fighter01` with clean non-zero exit (exit code 1). Negative screenshot captures blank pad with no sprite rendered.
  - Durable evidence recorded and verified in [`artifacts/runtime/rmxp/character/verification_evidence.json`](../artifacts/runtime/rmxp/character/verification_evidence.json).

## 4. RPG Maker VX (RGSS2) Standard 8-Character Slice (Task 5)
- **Shared Canonical Source:** Reuses the exact same canonical `test.calibration.walking-character` raw source (SHA-256: `78ad9a170ac0ba06eb4756f9c9c19923e754e82c22025dab7dfbc46de5c1b790`).
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
  - Executed using pinned `mkxp-z` (commit `826929eeb3ebc4b887c011604919217a790770f4`) in RGSS2 mode (`rgssVersion: 2`, screen resolution $544 \times 416$) against clean-room test harness ([`tests/fixtures/rmvx_character_min/`](../tests/fixtures/rmvx_character_min/)).
  - Positive control: Renders $288 \times 256$ sheet centered at $(128, 80)$ over high-contrast test pad $(116, 68, 312 \times 280)$ with 4 distinct corner alignment markers. Verified 100% pixel composite match across the $288 \times 256$ region against underlying pad, verified all 8 character block placements, and verified directional arrow orientations and transparency notches.
  - Negative control: With empty RTP, `Bitmap.new` raises `Errno::ENOENT`, logged as `SUPERRTP_RMVX_MISSING_ASSET: No such file or directory - Graphics/Characters/Actor1` with clean non-zero exit (exit code 1). Negative screenshot captures blank pad with no sprite rendered.
  - Durable evidence recorded and verified in [`artifacts/runtime/rmvx/character/verification_evidence.json`](../artifacts/runtime/rmvx/character/verification_evidence.json).

## 5. RPG Maker VX Ace (RGSS3) Standard 8-Character Slice (Task 6)
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
  - Executed using pinned `mkxp-z` in RGSS3 mode (`rgssVersion: 3`, screen resolution $544 \times 416$) against clean-room test harness ([`tests/fixtures/rmvxace_character_min/`](../tests/fixtures/rmvxace_character_min/)).
  - Startup verified via explicit mkxp-z startup log: `RGSS version 3 (RPG Maker VX Ace) `.
  - Positive control renders $288 \times 256$ sheet centered at $(128, 80)$ on pad; 100% composite match and alpha transparency verified.
  - Negative control isolates missing asset with deterministic diagnostic `SUPERRTP_RMVXACE_MISSING_ASSET: No such file or directory - Graphics/Characters/Actor1` and exit code 1.
  - Durable evidence recorded and verified in [`artifacts/runtime/rmvxace/character/verification_evidence.json`](../artifacts/runtime/rmvxace/character/verification_evidence.json).

## 6. WOLF RPG Editor v3 Character / CharaChip Slice (Task 7)
- **First Non-RPG-Maker Engine Family Vertical Slice:**
  - Establishes native support for WOLF RPG Editor v3 (`wolf`) directly from canonical walking character semantics (`test.calibration.walking-character`, character index 0).
  - Validates WOLF's native resource model: direct relative lookup under project directories (e.g. `Data/CharaChip/SuperRTP_Calibration.png`), distinct from RGSS RTP search-path fallbacks.
- **Physical CharaChip Layout & Packing Geometry:**
  - Standard 3-pattern $\times$ 4-direction character chip ($72 \times 128$ pixels, 12 cells of $24 \times 32$ pixels).
  - Row order:
    - **Row 0**: Facing **Down** (`v`, pattern numbers 1, 2, 3)
    - **Row 1**: Facing **Left** (`<`, pattern numbers 4, 5, 6)
    - **Row 2**: Facing **Right** (`>`, pattern numbers 7, 8, 9)
    - **Row 3**: Facing **Up** (`^`, pattern numbers 10, 11, 12)
  - Column order:
    - **Column 0**: Step Left
    - **Column 1**: Idle / Standing (Default direction facing)
    - **Column 2**: Step Right
- **Cross-Target Semantic Invariants:**
  - The 12 cells of WOLF CharaChip are byte-for-byte identical to the top-left $72 \times 128$ block of both RPG Maker VX (`rmvx`) and RPG Maker VX Ace (`rmvxace`) `Actor1.png` sheets.
  - The 12 cells match the RMXP walking frames (Step Left, Idle, Step Right = RMXP columns 3, 0, 1 for directions Down, Left, Right, Up).
- **Target Pack & Slot Mapping:**
  - `wolf`: Emits `Data/CharaChip/SuperRTP_Calibration.png` (SHA-256: `da3f32ef170575ff49abb04197413b663b1010735154ac2435771eeab02dc6e7`), 32-bit truecolor RGBA (Color Type 6, bit depth 8, no PLTE, no tRNS).
  - Policy: `rm2k_char0_to_wolf3_p3_d4_character_v1`.
- **Runtime & Visual Verification (Official WOLF Game.exe v3.717 under Wine/Xvfb):**
  - Executed using the official WOLF RPG Editor v3.717 runtime (`Game.exe`, SHA-256: `91821bd2439f562811060904498086709b8ac603640551e4f2fca45a0ff5f999`).
  - Native clean-room fixture ([`tests/fixtures/wolf_character_min/`](../tests/fixtures/wolf_character_min/)) with GuruGuru MIDI popup suppressed (`Game.dat` byte 17=0 and byte 20=0) and boot CommonEvent (ID 0) configured to run `parallel_process_always` (`0x23`).
  - Positive composite control: Renders 4 directions on Pad 1 (Down, Left, Right, Up) and 3 walking animation phases on Pad 2 (Step Left, Idle, Step Right) over high-contrast test pad `Data/Picture/test_pad.png` with 8 corner alignment markers. Verified 100% pixel composite match at 2x integer scaling ($640 \times 480$), opaque sprite equality, transparent alpha revealing pad color, directional chevron orientation, and walking step foot differentiation.
  - Individual directional & walking phase screenshots captured and verified:
    - [`wolf_character_down.png`](../artifacts/runtime/wolf/character/wolf_character_down.png) (Down Idle, Pattern 2)
    - [`wolf_character_left.png`](../artifacts/runtime/wolf/character/wolf_character_left.png) (Left Idle, Pattern 5)
    - [`wolf_character_right.png`](../artifacts/runtime/wolf/character/wolf_character_right.png) (Right Idle, Pattern 8)
    - [`wolf_character_up.png`](../artifacts/runtime/wolf/character/wolf_character_up.png) (Up Idle, Pattern 11)
    - [`wolf_character_walk_step1.png`](../artifacts/runtime/wolf/character/wolf_character_walk_step1.png) (Down Step Left, Pattern 1)
    - [`wolf_character_walk_step2.png`](../artifacts/runtime/wolf/character/wolf_character_walk_step2.png) (Down Step Right, Pattern 3)
  - Negative control: With `Data/CharaChip/SuperRTP_Calibration.png` omitted, WOLF runtime halts and renders native green error banner (`LoadGraphic ERROR: Cannot find the following files` / `ERROR: Cannot find [CharaChip/SuperRTP_Calibration.png]`) at screen region $y=192..288$ on black background. Verified in [`wolf_character_negative_control.png`](../artifacts/runtime/wolf/character/wolf_character_negative_control.png).
  - Game.exe runs in a dedicated Wine prefix (`.cache/wineprefix`) that sees only Wine's bundled fonts, so the `RESULT:72 / 128` lookup text renders identically on every host (see [engine-facts.md](engine-facts.md)).
  - Durable cryptographic evidence recorded and verified in [`artifacts/runtime/wolf/character/verification_evidence.json`](../artifacts/runtime/wolf/character/verification_evidence.json).
