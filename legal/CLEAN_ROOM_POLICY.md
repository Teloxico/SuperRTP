# SuperRTP Clean-Room Policy

## 1. Core Invariant

SuperRTP **MUST** contain zero proprietary RTP creative content.

Under no circumstances may any contributor, human or automated agent:
- Copy, trace, redraw, recolor, remix, extract, or AI-transform redistributable creative assets from proprietary RPG Maker or WOLF RPG Editor materials.
- Use proprietary RTP creative assets as generation references, control nets, or image-to-image inputs.
- Import or adapt assets from OpenRTP or other reverse-engineered packs whose licensing or clean-room status is suspect.

## 2. Permissible Asset Provenance

Every creative asset entering SuperRTP must have documented provenance in `registry/provenance/<asset-id>.json` conforming to `schemas/provenance.schema.json`.

Supported source types:
1. **`project_synthetic`**: Pure geometric, algorithmic, or code-generated assets created specifically for this project (e.g. calibration sheets).
2. **`externally_licensed`**: Assets created by external artists with verified redistribution rights (e.g., CC0-1.0, CC-BY, MIT, or custom open-game-art licenses). Ambiguous licenses ("free for non-commercial", "free for games") do not permit raw asset redistribution and are prohibited.
3. **`ai_generated`**: Original assets synthesized via AI models without proprietary RTP reference materials, accompanied by model name/version, prompt, seed, and date.

## 3. Functional Interoperability

Clean-room rules apply to creative expression, not functional interoperability.
The following functional facts are documented and implemented for compatibility:
- Slot filenames, relative directory layouts, and case-sensitive aliases.
- Pixel dimensions, frame grids, animation step ordering, and directional row mapping.
- Color depth, indexed palette constraints, and engine-specific transparency conventions.

## 4. Verification and Enforcement

Every build of a target RTP pack is validated deterministically:
- `tools/schema_validator.py` enforces provenance schema constraints.
- `tools/validate_target.py` verifies clean-room attestations (`proprietary_rtp_derived: false`, `openrtp_derived: false`).
- Negative controls and runtime test fixtures must verify that missing assets are handled gracefully without silent leakage.
