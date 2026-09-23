# Engine Compatibility Facts and Sources

Every engine rule that SuperRTP code relies on, with the primary source it was checked
against. When a rule in `tools/` or `registry/` changes, update the matching entry here.

Research date: 2026-09-23. Pinned versions: EasyRPG Player `0.8.1.1`,
mkxp-z `826929eeb3ebc4b887c011604919217a790770f4`, WOLF RPG Editor `3.717`.

Source preference follows `AGENTS.md` section 5: upstream source code and official
documentation first. Where an engine's behavior lives in proprietary default scripts
(RGSS1/2/3), the fact below is a functional interoperability fact (which pattern index is
drawn); no script text is copied into this repository.

## RPG Maker 2000 / 2003 (EasyRPG Player 0.8.1.1)

| Fact | Where SuperRTP relies on it | Source |
|---|---|---|
| RTP alias rows: 2k CharSet `主人公1 / actor1 / chara1`; 2k3 adds `hero1 / protagonist1 / 주인공1 / 主角1` | `registry/slots/rm2000.json`, `rm2003.json` | EasyRPG `src/rtp_table.cpp` lines 117 and 1247 at tag `0.8.1.1` |
| RTP alias rows: 2k ChipSet `基本 / world / basis`; 2k3 `基本 / world / main / world / basic / 기본 / 基本` | same | `src/rtp_table.cpp` lines 323 and 1255 |
| Paletted PNGs: only palette index 0 is transparent; every other index is drawn opaque (tRNS and alpha are ignored) | `transforms.rgba_to_indexed_png` rejects partially transparent source pixels | `src/image_png.cpp` `ReadPalettedData`, lines 137-168 |
| Facing enum `Up=0, Right=1, Down=2, Left=3`; sprite row = facing | Canonical sheet row order `UP, RIGHT, DOWN, LEFT` | `src/game_character.h` line 905; `src/sprite_character.cpp` lines 40-43 |
| Source column = animation frame; a stopped character resets to `Frame_middle` (column 1) | Canonical column 1 is `IDLE` | `src/sprite_character.cpp` line 43; `src/game_character.h` line 1227 (`SetAnimFrame(Frame_middle)`) |
| `--log-file` opens the log in append mode (`std::ios_base::app`) | Runtime capture deletes the previous log before each run | `src/game_config.cpp` line 353 |

## RPG Maker XP / VX / VX Ace (mkxp-z 826929e)

| Fact | Where SuperRTP relies on it | Source |
|---|---|---|
| Config keys `rgssVersion`, `gameFolder`, `customScript`, `pathCache`, `RTP` (list of asset search paths) | Runtime harness `mkxp.json` generation | mkxp-z `mkxp.json` sample at the pinned commit |
| With `workdir_current`, `gameFolder` resolves against the working directory | Harness launches mkxp-z from a temporary working directory | same file, header comment |
| XP character sheet: 4x4 cells, rows down, left, right, up | RMXP transform row order | RPG Maker XP help, "Material Specifications" (mirror: rpg-maker.fr/dl/monos/aide/xp/source/rpgxp/material.html) |
| XP draws column `pattern`; a stopped character uses pattern 0, walking cycles 0,1,2,3 | **Open issue**, see below | RGSS1 default `Sprite_Character` (`sx = pattern * width/4`) and `Game_Character 1` (`@original_pattern = 0`), as found in public project copies |
| VX / VX Ace sheet: 8 characters (4 across, 2 down), each 3 patterns x 4 directions (down, left, right, up) | VX-family transform | VX Ace help "Resource Specifications", as quoted on rpgmaker.net topic 11130 |
| VX / VX Ace stopped pattern is 1 (middle column) | VX-family column order `STEP_LEFT, IDLE, STEP_RIGHT` | RGSS2/RGSS3 default `Game_CharacterBase` (`@original_pattern = 1`) |
| `$` prefix = one character per file; `!` prefix = no 4-pixel offset, no bush translucency | Not implemented (out of scope) | VX Ace help "Resource Specifications" |

### Open issue: RMXP stopped pose

The RMXP transform (`rm2k_to_rgss1_character_4x4`) writes columns
`STEP_LEFT, IDLE, STEP_RIGHT, IDLE`. Because RGSS1 shows pattern 0 for a stopped
character, a standing XP character shows the `STEP_LEFT` frame. A layout of
`IDLE, STEP_LEFT, IDLE, STEP_RIGHT` (or an equivalent that puts `IDLE` in column 0)
would match the engine. Changing it alters the RMXP target bytes and its runtime evidence,
so it is tracked as a separate decision rather than folded into refactoring.

## WOLF RPG Editor 3.717

| Fact | Where SuperRTP relies on it | Source |
|---|---|---|
| 3-pattern / 4-direction CharaChip: 3 columns x 4 rows, rows down, left, right, up | WOLF transform | silversecond.com/WolfRPGEditor/Help/06material.html; Guide/MAKEMAT_002.html |
| Animation plays B, A, B, C, B (middle column is the rest frame) | WOLF column order `STEP_LEFT, IDLE, STEP_RIGHT` | Guide/MAKEMAT_002.html section 1 |
| Filenames ending `T.png`, `TX.png` add stopped-pose columns; `$.png` disables division | Validator rejects these suffixes for the standard CharaChip slot | Help/06material.html; Guide/MAKEMAT_002.html sections 3-4 |
| Each pattern should be an even number of pixels | 24x32 cells satisfy this | Help/06material.html |
| RPG Maker 200x sheets use rows up, right, down, left and need conversion | Independent confirmation of the canonical 2k row order | Guide/MAKEMAT_002.html section 5 |

## Host tooling

| Fact | Where SuperRTP relies on it | Source |
|---|---|---|
| X.Org servers accept `-displayfd FD` and write the display number they bound once ready | Runtime harness allocates Xvfb displays without guessing numbers or deleting lock files | `Xserver(1)` man page (x.org), verified against the local Xvfb |
| `Game.exe` from the WOLF 3.717 mini archive is a 32-bit (PE32, i386) executable | Wine on the host must be able to run 32-bit programs (WoW64 or a wine32 install) | `file Game.exe` on the checksum-verified binary |
