# Asset generation

How SuperRTP produces replacement art for the whole filename inventory
(`registry/upstream-assets/`: 2,934 image paths across the six engines; the 2,738 audio
paths are inventoried but not generated).
The tooling lives in `tools/asset_generation/` (see its README for commands).

## Model: FLUX.2 [klein] 4B

| Decision | Reason | Source |
|---|---|---|
| FLUX.2 [klein] **4B**, revision `e7b7dc27f91deacad38e78976d1f2b499d76a294` | The only FLUX.2 weights under **Apache-2.0**. The generated assets must be redistributable without conditions | Model card and `LICENSE.md`, huggingface.co/black-forest-labs/FLUX.2-klein-4B |
| Not FLUX.2 [dev] or [klein] 9B | Both use the FLUX Non-Commercial License, which conflicts with an unrestricted asset pack (legal/CLEAN_ROOM_POLICY.md) | Model cards of FLUX.2-dev and FLUX.2-klein-9B (`license: other`, non-commercial) |
| 4 steps, guidance 1.0 | The distilled model's documented settings | Model card usage example |
| Transformer and Qwen3 text encoder in 4-bit NF4 (bitsandbytes), model CPU offload | The card asks for ~13 GB of VRAM. This PC has an 8 GB RTX 4070 Laptop GPU; measured peak is about 5 GB | Local measurement, `nvidia-smi` |
| Prompts: subject first, then pose, style, setting and light; 30-80 words; no negative wording; hex colours tied to objects | FLUX.2 has no negative prompts and weights early words most, and klein has no prompt upsampling | docs.bfl.ai/guides/prompting_guide_flux2, docs.bfl.ai/flux_2/flux2_overview |

Measured speed on this machine is about 5 s per 768x768 or 512x768 image, 7 s for a
view conditioned on a reference image, and 7.5 s per 1024x768 image. The full plan of
4,311 concepts takes roughly eight hours.

The environment is project-local and git-ignored. `tools/asset_generation/setup_flux.sh`
creates `.cache/flux/venv` with pinned versions and downloads the pinned model to
`.cache/flux/models/`.

## Art direction

`specs/generation/art-direction.v1.json` holds all prompt text, written for this
project:

- **Style guide:** the world, a master palette with hex values, and the treatments for
  sprites, scenes, portraits and textures.
- **Family briefs:** composition, pose and background for each asset family.
- **Subject descriptions:** one original description for every subject in the
  inventory (760 entries). Numbered series such as icons or slimes have lists, so each
  file gets a different subject.

A description depicts a generic, folkloric or invented archetype. Filename words are
only a starting point: creator tags and personal names in filenames are dropped, and
the description never names or imitates an existing product, franchise, artist or
asset. A test fails if any job lacks an authored brief or if a prompt names an engine
or vendor.

## From concept to engine asset

FLUX draws; deterministic code (`flux_structure.py`) enforces everything an engine
depends on:

| Family | Concept | Structuring |
|---|---|---|
| creature, icon | one subject on a flat key colour | key out backdrop and shadows (hue dominance, border-connected) and fit to size |
| charset (all engines) | three images per character on key colour: a front view, then side (facing left) and back views conditioned on that front | mirror left→right. Idle frames from the views, steps from a 1-px leg offset. Packed with `transforms.pack_sheet_rgba` and each engine's `SheetLayout` |
| battle-character | one side-view sprite | 8 pose rows × 3 frames derived by transforms (lunge, knockdown, recoil, darken) |
| faces, portrait | one portrait per cell | head-crop and fit into the 4-column grid |
| scene, fog, overlay, transition | opaque painting | cover-crop to size. Fog alpha from brightness, overlay with a clear centre, transition to grayscale |
| effect | one burst on black | alpha from brightness, 5-column frame grid growing then fading |
| tiles, autotile | seamless material textures | each tile cell filled from the textures |

### Character views

A single "model sheet" prompt made FLUX draw the front as a three-quarter view facing
left, so the down-facing and left-facing rows of every character showed nearly the same
pose. Each character is therefore three jobs (`flux_jobs.VIEWS`):

- **Front:** a strictly frontal, symmetrical full-body view from the text description.
- **Side and back:** the generated front is passed as the only image input
  (`Flux2KleinPipeline(image=[front])`), with a prompt asking for the same character in
  left profile or from behind. This keeps the three views one design.
- **View check** (`flux_structure.view_check`): character front and back views must be
  mirror-symmetric (silhouette IoU with the mirror image ≥ 0.9 and colour symmetry
  ≥ 0.8); a side view must be at least 0.05 less symmetric than its front. A failing
  view is re-rendered with other seeds, up to four attempts. If all fail, the
  best-scoring attempt is kept and its sidecar records `view_check.passed: false`.
  Tails and staffs held to one side make some true front views fail; those are kept
  this way rather than dropped.

RM2000/2003 targets are quantized to at most 255 colours plus transparency, as their
indexed PNG format requires. The window skins, masks, the weapon sheet and the icon
atlas stay procedural. The manifest's `visual_source` field says, per path, whether an
image is `flux2-klein-4b` or `procedural`.

## Provenance

- **Concept sidecars:** each concept has a sidecar (`.cache/flux/concepts/<id>/<part>.json`)
  recording the prompt, seed, steps, guidance, quantization, model and revision,
  library versions, GPU and image SHA-256. `image_inputs` is null, except for side
  and back views, where it names the front view job and its image SHA-256. The model
  never receives any other image.
- **Structured sidecars:** these bind the concept hashes and the structuring algorithm
  version.
- **Pack manifest:** the v2 manifest (`artifacts/generation/full-inventory/v2/manifest.json`)
  binds every output file, its source and the art-direction hash.
- **Release archives:** `tools/release/package_release.py` packages each pack only after
  the runtime gate passed on that exact manifest (see [installing.md](installing.md)).

## Runtime gate

`tools/verify_generated_packs.py` runs the real engines against the generated packs,
using clean-room fixtures:

| Case | What must happen |
|---|---|
| `rtp-path` (RM2000/2003) | EasyRPG loads each pack's CharSet and ChipSet given with `--rtp-path`. The fixtures request legacy alias names (Basis, Hero1, Main), which EasyRPG resolves to the official names in the pack (World, Actor1). The log shows the map loaded and no "Image not found"; the screen shows the map and no warning banner. |
| `installed` (RM2000/2003) | The pack's release archive is built and extracted, and its own `install.py` installs it: to `$XDG_DATA_HOME/rtp/<2000\|2003>`, as an HKCU value in a Wine prefix, or as an HKLM 32-bit value in a Wine prefix. EasyRPG then runs with no RTP option and must add the installed folder to its RTP path and draw the map. `install.py --uninstall` must then remove the files and the registry value. |
| `character` (XP/VX/VX Ace) | mkxp-z's `Bitmap.new` of the character slot resolves through the pack at the pack file's exact size. |
| `scan` (XP/VX/VX Ace) | Every image of the pack is loaded by mkxp-z (`tests/fixtures/rgss_pack_scan`) through the RTP list that `install.py --mkxp-json` wrote, and every size must equal the manifest's. A contact sheet of 48 sampled images is captured. |
| `wolf` | WOLF's `Game.exe` (Wine) draws a generated CharaChip in the WOLF fixture; all seven event cells must match the sheet pixel for pixel and the engine must report 72x128. WOLF has no RTP lookup, so this checks the image format, not an installation. |

The report (`artifacts/generation/full-inventory/v2/runtime-gate.json`) binds each
loaded file's SHA-256, the screenshots and the engine versions. The service runs the
gate at completion and records the result in `.cache/flux/COMPLETE.json`.

The VX/VX Ace calibration fixtures expect the 288x256 calibration sheet (24x32 frames).
The generated sheets follow the stock VX layout of 32x32 frames (384x256). RGSS2/3 derive
the frame size from the bitmap, so both load. The gate accepts the fixtures' size-mismatch
exit only when the loaded size equals the pack file's.

## Running unattended

`tools/asset_generation/run_flux_service.sh --install` installs `superrtp-flux.service`, a
systemd user service that restarts after failures and starts at login. It runs
`flux_worker.py --until-complete`, which does the following in order:
1. Generates every concept, retrying failed jobs for up to three passes.
2. Structures the concepts, then builds and verifies the packs.
3. Runs the runtime gate.
4. Writes `.cache/flux/COMPLETE.json` and frees the model and its environment (~12 GB).
   `setup_flux.sh` recreates them.

The service then disables itself. Follow progress in `.cache/flux/status.json` or
`.cache/flux/worker.log`.

## Known limits

- **Walking animation:** steps are synthesised from one standing view per direction, a
  one-pixel leg offset rather than drawn strides. The right-facing row mirrors the left
  one.
- **Facing:** the view check proves the side view is not frontal, but not that it faces
  left rather than right; that relies on the prompt. It has faced left in every sample
  inspected.
- **Battle poses:** these are transforms of a single sprite.
- **Tile sheets:** cells are filled with generated material textures. They are not
  hand-designed tile layouts with engine semantics (edges, autotile transitions,
  passability art). Autotiles only get a darker rim.
- **Audio:** out of scope. The 2,738 inventoried audio paths are listed in the manifest's
  `audio_not_generated` backlog and no audio file is written.
