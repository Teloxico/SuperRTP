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
| Paletted PNGs: only palette index 0 is transparent; every other index is drawn opaque (tRNS and alpha are ignored) | `transforms.transform_rgba_to_indexed_png` rejects partially transparent source pixels | `src/image_png.cpp` `ReadPalettedData`, lines 137-168 |
| Facing enum `Up=0, Right=1, Down=2, Left=3`; sprite row = facing | Canonical sheet row order `UP, RIGHT, DOWN, LEFT` | `src/game_character.h` line 905; `src/sprite_character.cpp` lines 40-43 |
| Source column = animation frame; a stopped character resets to `Frame_middle` (column 1) | Canonical column 1 is `IDLE` | `src/sprite_character.cpp` line 43; `src/game_character.h` line 1227 (`SetAnimFrame(Frame_middle)`) |
| `--log-file` opens the log in append mode (`std::ios_base::app`) | Runtime capture deletes the previous log before each run | `src/game_config.cpp` line 353 |

## RPG Maker XP / VX / VX Ace (mkxp-z 826929e)

| Fact | Where SuperRTP relies on it | Source |
|---|---|---|
| Config keys `rgssVersion`, `gameFolder`, `customScript`, `pathCache`, `RTP` (list of asset search paths) | Runtime harness `mkxp.json` generation | mkxp-z `mkxp.json` sample at the pinned commit |
| With `workdir_current`, `gameFolder` resolves against the working directory | Harness launches mkxp-z from a temporary working directory | same file, header comment |
| XP character sheet: 4x4 cells, rows down, left, right, up | RMXP transform row order | RPG Maker XP help, "Material Specifications" (mirror: rpg-maker.fr/dl/monos/aide/xp/source/rpgxp/material.html) |
| XP draws column `pattern`; a stopped character uses pattern 0, walking cycles 0,1,2,3 | RMXP column order `IDLE, STEP_RIGHT, IDLE, STEP_LEFT`, see below | RGSS1 default `Sprite_Character` (`sx = pattern * width/4`) and `Game_Character 1` (`@original_pattern = 0`), as found in public project copies |
| VX / VX Ace sheet: 8 characters (4 across, 2 down), each 3 patterns x 4 directions (down, left, right, up) | VX-family transform | VX Ace help "Resource Specifications", as quoted on rpgmaker.net topic 11130 |
| VX / VX Ace stopped pattern is 1 (middle column) | VX-family column order `STEP_LEFT, IDLE, STEP_RIGHT` | RGSS2/RGSS3 default `Game_CharacterBase` (`@original_pattern = 1`) |
| `$` prefix = one character per file; `!` prefix = no 4-pixel offset, no bush translucency | Not implemented (out of scope) | VX Ace help "Resource Specifications" |

### RMXP column order (resolved 2026-09-23)

RGSS1 shows pattern 0 for a stopped character and walks patterns 0, 1, 2, 3. The 2k family
(EasyRPG `game_character.h` line 1220, liblcf `EventPage::Frame_*`) rests on `Frame_middle`
and advances `left=0, middle=1, right=2, middle2=3` modulo 4, so from rest it plays
IDLE, STEP_RIGHT, IDLE, STEP_LEFT. The RMXP transform therefore writes columns
`IDLE, STEP_RIGHT, IDLE, STEP_LEFT` (policy `rm2k_to_rgss1_character_4x4_idle_first_v2`).
The earlier layout `STEP_LEFT, IDLE, STEP_RIGHT, IDLE` made standing XP characters show a
mid-stride frame.
| VX/VX Ace character sheets may be any size: the frame is 1/12 of the width and 1/8 of the height (1/3 and 1/4 for `$` single-character files). The stock sprite is 32x32, i.e. a 384x256 sheet | Generated VX/VX Ace sheets use 32x32 frames (384x256); the 288x256 calibration sheet (24x32 frames) loads for the same reason | RPG Maker VX Ace manual, Resource Standards (rpgvxace/6100_resource.html); stock size per community references (RPG Maker forums, 2018) |

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
| Wine resolves a requested font face through the host's fontconfig. The WOLF fixture's lookup text uses the "Courier" face, which became Courier New where the Microsoft core fonts are installed and another font elsewhere | WOLF runs point `FONTCONFIG_FILE` at a private configuration with no font directories, so only Wine's bundled fonts are visible (`tools/wolf_runtime.py`) | `WINEDEBUG=+font` traces (`NtGdiHfontCreate ... L"Courier"`, `select_font Chosen: ...`) on the local host; CI screenshots of the same fixture |
| Ubuntu 24.04 (noble) ships `wine32:i386` (Wine 9.0) in universe; it needs `dpkg --add-architecture i386` | CI installs `wine wine32:i386` | packages.ubuntu.com/noble/wine32 |

## Where runtimes find an installed RTP

Used by `tools/release/install.py`; see [installing.md](installing.md) for what is verified.

| Fact | Where SuperRTP relies on it | Source |
|---|---|---|
| EasyRPG builds for Linux, BSD and macOS define `USE_WINE_REGISTRY` and `USE_XDG_RTP` | The installer's default on non-Windows desktops is the XDG folder, macOS included | `src/system.h` at `0.8.1.1` ("Everything not catched above, e.g. Linux/*BSD/macOS") |
| EasyRPG adds `$XDG_DATA_HOME/rtp/<2000\|2003>` (default `~/.local/share/rtp/...`) and each `$XDG_DATA_DIRS/rtp/...` that exists, after `--rtp-path` and `RPG_RTP_PATH`, `RPG2K_RTP_PATH`, `RPG2K3_RTP_PATH` | Default install folder; the runtime gate isolates these variables | `src/filefinder_rtp.cpp` at `0.8.1.1` |
| EasyRPG reads `Software\ASCII\RPG2000` `RuntimePackagePath` and `Software\KADOKAWA\RPG2000` for 2000, and `Software\Enterbrain\RPG2003` `RUNTIMEPACKAGEPATH` and `Software\KADOKAWA\RPG2003` `RuntimePackagePath` for 2003, from HKCU then HKLM in the 32-bit view, plus `Software\EasyRPG\RTP` `path` | Registry values the installer writes | `src/filefinder_rtp.cpp` at `0.8.1.1` |
| On non-Windows, EasyRPG reads those values from `$WINEPREFIX/user.reg` (HKCU) or `system.reg` (HKLM, `Software\` redirected to `Software\Wow6432Node\` in a 64-bit prefix), and maps a `Z:\` path to `/` | `--wine-prefix` installs, and the gate's Wine cases | `src/registry_wine.cpp` at `0.8.1.1` |
| The RGSS `Game.exe` takes the RTP name from `Game.ini` (`RTP1`–`RTP3` in XP, `RTP` in VX and VX Ace; standard names `Standard`, `RPGVX`, `RPGVXAce`) and reads the folder from that string value under `HKLM\SOFTWARE\Enterbrain\RGSS\RTP`, `RGSS2\RTP` or `RGSS3\RTP`; installers default to `[CommonFilesFolder]\Enterbrain\RGSS*\<name>` | `--register machine` for XP, VX and VX Ace | RGSS reference manuals, "RGSS Specifications", RTP section (XP, VX and VX Ace help files; mirrors at rpg-maker.fr and enls.gitbook.io) |
| mkxp-z takes RTP folders or `.zip` files from the `"RTP"` list of `mkxp.json`, and merges a second `mkxp.json` from the game's user data folder | `--mkxp-json` | `mkxp.json` sample and `src/config.cpp` at `826929e` |
| Wine's `reg.exe` accepts `/reg:32` and writes HKLM values to `Wow6432Node` in a 64-bit prefix; its server saves `user.reg`/`system.reg` shortly after its last client exits | The installer's Wine path; the gate waits for the change to reach the files | Local Wine run (`reg add ... /reg:32`, then `system.reg`) |
