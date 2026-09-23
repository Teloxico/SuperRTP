# Asset-generation pipeline

Every inventoried visual is drawn by **FLUX.2 [klein] 4B** (Apache-2.0) from original
art direction, then forced into the exact engine format by deterministic code. A few purely
structural visuals stay procedural; audio is not generated. Every manifest entry records
which source produced it. See [docs/asset-generation.md](../../docs/asset-generation.md)
for the design, the model choice and known limits.

```
specs/generation/art-direction.v1.json   style guide, family briefs, one description per subject
  -> flux_jobs.py        plans 2,797 text-only concept jobs (prompt, size, key colour, seed)
  -> flux_worker.py      runs FLUX.2 [klein] 4B locally; .cache/flux/concepts/ + provenance sidecars
  -> flux_structure.py   keys, crops, fits and lays out frames; .cache/flux/structured/
  -> generate_full_inventory.py --spec specs/generation/full-inventory.v2.json
                         encodes every compatibility path into artifacts/generation/full-inventory/v2
```

## Running it

```bash
tools/asset_generation/setup_flux.sh      # once: .cache/flux/venv + pinned model (~16 GB)
setsid nohup .cache/flux/venv/bin/python -u tools/asset_generation/flux_worker.py --watch \
  > .cache/flux/worker.log 2>&1 < /dev/null &
cat .cache/flux/status.json               # progress; failures go to .cache/flux/failures.jsonl
```

With `--watch` the worker keeps running. It structures finished concepts every 25 jobs.
After each full pass it rebuilds and verifies the v2 packs, then re-plans every five
minutes. Editing a description in the art-direction file regenerates exactly the jobs
whose prompt changed.

Manual steps, when needed:

```bash
.cache/flux/venv/bin/python tools/asset_generation/flux_worker.py --plan        # job counts, no model load
.cache/flux/venv/bin/python tools/asset_generation/flux_structure.py            # structure finished concepts
python3 tools/asset_generation/generate_full_inventory.py --write               # build packs (v2 spec)
python3 tools/asset_generation/generate_full_inventory.py --check               # verify packs
```

## Clean-room rules

- Prompts are text only. No image, proprietary or otherwise, is ever passed to the model.
- Descriptions are written for this project. They never name or describe an engine,
  product, franchise, artist or existing asset.
- `tests/test_full_inventory_generation.py` enforces the first two mechanically: every
  job must have an authored brief and no prompt may name an engine or vendor.
