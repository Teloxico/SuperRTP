# Upstream Creative-Asset Filename Inventory

This is SuperRTP's filename-only planning inventory for every engine target currently
declared in the repository. It contains **no upstream images, audio, or other creative
content**. The paths are functional interoperability facts used to plan independent
replacements.

Snapshot date: 2026-09-23.

## Complete pinned scope

| Target | Distribution represented | Creative media paths | Exact list |
|---|---|---:|---|
| `rm2000` | Current official English RPG Maker 2000 RTP download | 466 | [`rm2000.txt`](../registry/upstream-assets/rm2000.txt) |
| `rm2003` | Current official English RPG Maker 2003 RTP download | 676 | [`rm2003.txt`](../registry/upstream-assets/rm2003.txt) |
| `rmxp` | Official English XP RTP 1.04 | 882 | [`rmxp.txt`](../registry/upstream-assets/rmxp.txt) |
| `rmvx` | Official English VX RTP 1.02 | 439 | [`rmvx.txt`](../registry/upstream-assets/rmvx.txt) |
| `rmvxace` | Official English VX Ace RTP 1.00 | 748 | [`rmvxace.txt`](../registry/upstream-assets/rmvxace.txt) |
| `wolf` | Creative media under `Data/` in the official WOLF 3.717 full package | 645 | [`wolf.txt`](../registry/upstream-assets/wolf.txt) |
| **Total** |  | **3,856** | |

The official RM2000 Japanese plus RM2003 Japanese/Traditional Chinese columns add
1,816 localized path records, for **5,672 recorded names/paths** across the complete
scope below. They are aliases of the same semantic assets except for the one additional
Traditional Chinese RM2003 GameOver row.

Each text file is sorted, UTF-8, and contains one exact case-sensitive relative path
per line. `sources.json` records every source URL, archive SHA-256, output SHA-256,
count, and per-category count:

- [`sources.json`](../registry/upstream-assets/sources.json)

The five RPG Maker inventories come from the publisher-hosted packages linked on the
official [RTP download page](https://www.rpgmakerweb.com/run-time-package). The WOLF
inventory comes from the official maintainer's pinned `v3.717` full release. Generation
reads only installer/archive metadata; creative files are not copied into SuperRTP.

## Official RM2000 and RM2003 locale names

The current English packages are the canonical path lists above. Older games also use
publisher RTPs whose files have localized names. The two TSVs map the same semantic
rows without claiming that translated filenames are new creative works:

- [`rm2000-official-aliases.tsv`](../registry/upstream-assets/rm2000-official-aliases.tsv):
  all 465 English RTP media files and all 465 official Japanese names.
- [`rm2003-official-aliases.tsv`](../registry/upstream-assets/rm2003-official-aliases.tsv):
  all 675 English/Japanese rows and all 676 official Traditional Chinese names. The
  Traditional Chinese distribution has the additional `GameOver/遊戲結束2.png` row.

These mappings are derived from EasyRPG Player 0.8.1.1 `src/rtp_table.cpp`. Its Don
Miguel, RPG Advocate, Vlad, RPG Universe, Korean translation, and RM2000 add-on columns
are deliberately excluded: they are community distributions, not publisher RTP asset
inventories. Excluding them prevents third-party/ripped add-on names from being
misrepresented as official assets.

The root `icon.ico` in each RPG Maker list is package/project artwork, not a normal
runtime lookup slot. It is retained because the request covers every bundled creative
asset name.

## What is and is not counted

The inventory includes bundled creative media with these extensions: `.ico`, `.jpg`,
`.mid`, `.ogg`, `.png`, and `.wav`.

It excludes non-creative or non-runtime material:

- executables, RGSS DLLs, installers, and binary project/database files;
- readmes, EULAs, installer artwork, and documentation/guide screenshots;
- UmePlus and VL Gothic fonts and their license files (separately licensed open font
  dependencies, not proprietary replacement art);
- VX Ace's 22 bilingual `.txt` tile-label companions, which are editor descriptions,
  not engine-loaded creative assets;
- empty directories, including XP's `Graphics/Pictures/` directory.

The WOLF list needs a special qualification. WOLF does not have an external RTP search
package: these are project-local paths from the full editor/sample-data bundle, and
many files credit independent contributors. The list is a complete path inventory of
that pinned bundle, **not** a claim that every WOLF game looks up those names or that
all files share one proprietary owner/license. Each eventual replacement still needs
its own clean-room provenance.

## Verification and regeneration

Validate the committed inventories without downloading any upstream package:

```bash
python3 tools/validate_upstream_asset_inventory.py
```

The validator checks source-bound inventory hashes, exact counts, category totals,
sorting, uniqueness, path safety, Unicode normalization, allowed media types, and full
RM2000/RM2003 official-English alias coverage. `tests/test_foundation.py` runs the same
validation in the normal test suite.

The reproducible metadata reader is
[`generate_upstream_asset_inventory.py`](../tools/generate_upstream_asset_inventory.py).
It requires locally supplied, hash-matching official archives, EasyRPG's pinned source
file, `7z`, and `innoextract`. It intentionally does not download or commit upstream
creative content.

## How this should drive replacement work

These files are a backlog, not finished `registry/slots/` mappings. A path only proves
that a compatibility lookup or bundled material exists; it does not tell us what an
independent replacement should depict or sound like. Replacement work should proceed
category by category with neutral functional specifications, original/openly licensed
sources, provenance records, deterministic transforms, and real runtime verification.
