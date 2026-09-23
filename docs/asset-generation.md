# Asset generation

How SuperRTP produces replacement art for the whole filename inventory
(`registry/upstream-assets/`, 5,672 compatibility paths across the six engines).
The tooling lives in `tools/asset_generation/` (see its README for commands).

## Model: FLUX.2 [klein] 4B

| Decision | Reason | Source |
|---|---|---|
| FLUX.2 [klein] **4B**, revision `e7b7dc27f91deacad38e78976d1f2b499d76a294` | The only FLUX.2 weights under **Apache-2.0**. The generated assets must be redistributable without conditions | Model card and `LICENSE.md`, huggingface.co/black-forest-labs/FLUX.2-klein-4B |
| Not FLUX.2 [dev] or [klein] 9B | Both use the FLUX Non-Commercial License, which conflicts with an unrestricted asset pack (legal/CLEAN_ROOM_POLICY.md) | Model cards of FLUX.2-dev and FLUX.2-klein-9B (`license: other`, non-commercial) |
| 4 steps, guidance 1.0 | The distilled model's documented settings | Model card usage example |
| Transformer and Qwen3 text encoder in 4-bit NF4 (bitsandbytes), model CPU offload | The card asks for ~13 GB of VRAM. This PC has an 8 GB RTX 4070 Laptop GPU; measured peak is about 5 GB | Local measurement, `nvidia-smi` |
| Prompts: subject first, then pose, style, setting and light; 30-80 words; no negative wording; hex colours tied to objects | FLUX.2 has no negative prompts and weights early words most, and klein has no prompt upsampling | docs.bfl.ai/guides/prompting_guide_flux2, docs.bfl.ai/flux_2/flux2_overview |

Measured speed on this machine is about 5.5 s per 1024x512 or 768x768 image and about
7.5 s per 1024x768 image. The full plan of 2,797 concepts takes roughly five hours.

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
| charset (all engines) | three-view turnaround on key colour | split views by empty columns, then mirror left→right. Idle frames from the views, steps from a 1-px leg offset. Packed with `transforms.pack_sheet_rgba` and each engine's `SheetLayout` |
| battle-character | one side-view sprite | 8 pose rows × 3 frames derived by transforms (lunge, knockdown, recoil, darken) |
| faces, portrait | one portrait per cell | head-crop and fit into the 4-column grid |
| scene, fog, overlay, transition | opaque painting | cover-crop to size. Fog alpha from brightness, overlay with a clear centre, transition to grayscale |
| effect | one burst on black | alpha from brightness, 5-column frame grid growing then fading |
| tiles, autotile | seamless material textures | each tile cell filled from the textures |

RM2000/2003 targets are quantized to at most 255 colours plus transparency, as their
indexed PNG format requires. The window skins, masks, the weapon sheet and the icon
atlas stay procedural. The manifest's `visual_source` field says, per path, whether an
image is `flux2-klein-4b` or `procedural`.

## Provenance

- **Concept sidecars:** each concept has a sidecar (`.cache/flux/concepts/<id>/<part>.json`)
  recording the prompt, seed, steps, guidance, quantization, model and revision,
  library versions, GPU, image SHA-256, and `image_inputs: null`.
- **Structured sidecars:** these bind the concept hashes and the structuring algorithm
  version.
- **Pack manifest:** the v2 manifest (`artifacts/generation/full-inventory/v2/manifest.json`)
  binds every output file, its source and the art-direction hash. The packs remain
  `candidate-not-active`: the active target builder does not emit them until a runtime
  promotion gate approves their slot maps.

## Known limits

- **Walking animation:** steps are synthesised from one standing view per direction, a
  one-pixel leg offset rather than drawn strides. The right-facing row mirrors the left
  one.
- **Facing:** the side view relies on FLUX drawing "profile facing left" as asked. It
  has done so in the samples inspected, but the direction is not verified automatically.
- **Battle poses:** these are transforms of a single sprite.
- **Tile sheets:** cells are filled with generated material textures. They are not
  hand-designed tile layouts with engine semantics (edges, autotile transitions,
  passability art). Autotiles only get a darker rim.
- **Audio:** all audio is still procedural.

## Audio: candidate models (researched 2026-09-23, not yet installed)

The inventory needs MIDI music (`.mid` for RM2000/2003 and some XP/VX BGM), rendered
music loops (`.ogg`/`.wav` BGM, BGS, ME) and several hundred short sound effects. The
weights must allow redistributing their outputs, and training-data provenance matters
under legal/CLEAN_ROOM_POLICY.md.

| Use | Candidate | License | Fit for this PC | Notes |
|---|---|---|---|---|
| Music (BGM, BGS, ME) | **ACE-Step 1.5** (`ACE-Step/Ace-Step1.5`, turbo DiT + 0.6B/1.7B planner LM) | MIT | Card states under 4 GB VRAM | Card states commercial use of output is allowed and training data is licensed, royalty-free or synthetic. Strongest provenance of the music models checked |
| Sound effects | **Ming-omni-tts-0.5B** (`inclusionAI/Ming-omni-tts-0.5B`) | Apache-2.0 | 0.5B, fits easily | Unified speech, sound and music model; SFX quality not yet evaluated |
| Sound effects (higher quality) | MOSS-SoundEffect (`OpenMOSS-Team/MOSS-SoundEffect`) | Apache-2.0 | 8.4B parameters, needs 4-bit to fit 8 GB (unverified) | Dedicated SFX model with duration control |
| Sound effects, alternative | MiDashengLM-Gen (`mispeech/midashenglm-gen`) | Apache-2.0 | ~6 GB checkpoint; upstream quotes ~12 GB fp32 | 16 kHz output |
| MIDI | text2midi (`amaai-lab/text2midi`) | Apache-2.0 | small | Text-conditioned. **Trained on MidiCaps (Lakh MIDI), which contains copyrighted songs.** Treat as a legal question before use |
| MIDI, alternative | skytnt/midi-model | Apache-2.0 | 233M | Not text-conditioned; trained on the Los Angeles MIDI Dataset (same provenance question) |

Excluded:
- **Non-commercial weights:** MusicGen and AudioGen (CC-BY-NC), Omni2Sound (CC-BY-NC).
- **Stability AI Community License:** Stable Audio Open (gated) and TangoFlux, which is
  built on it.

**Open question:** whether EasyRPG resolves a music slot by name across extensions,
which would let rendered `.ogg` stand in for `.mid`. This is unverified and must be
checked in `src/filefinder.cpp` before relying on it.
