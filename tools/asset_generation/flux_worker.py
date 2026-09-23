#!/usr/bin/env python3
"""
Long-running FLUX.2 [klein] 4B concept generator for the full asset inventory.

Run it with the generation environment (tools/asset_generation/setup_flux.sh):

    .cache/flux/venv/bin/python tools/asset_generation/flux_worker.py --watch

It loads the pinned model once, walks the job plan (tools/asset_generation/flux_jobs.py)
in priority order and writes, per job:

    .cache/flux/concepts/<creative_id>/<part>.png    the generated concept, no metadata
    .cache/flux/concepts/<creative_id>/<part>.json   provenance: model, revision, prompt,
                                                     seed, steps, quantization, versions,
                                                     image SHA-256; written last, so its
                                                     presence marks the job done

A job is redone only when its prompt, size or seed changes (prompt_sha256). With
--watch the worker re-plans every WATCH_INTERVAL_S seconds and keeps running, so edited
prompts or new inventory entries are picked up without a restart. Progress goes to
.cache/flux/status.json; a job that raises is recorded in .cache/flux/failures.jsonl
and reported in the status, never skipped silently.

Model choice (docs/asset-generation.md): FLUX.2 [klein] 4B is the only FLUX.2 variant
under Apache-2.0 (the 9B and dev weights use the FLUX Non-Commercial License), which
keeps every generated asset redistributable. On an 8 GB GPU the transformer and the
Qwen3 text encoder are loaded 4-bit (bitsandbytes NF4) with model CPU offload.
"""

import argparse
import datetime
import hashlib
import json
import os
import sys
import time
import traceback

TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS_DIR)

from asset_generation import flux_jobs  # noqa: E402
from asset_generation import generate_full_inventory as inventory  # noqa: E402
from repo import REPO_ROOT  # noqa: E402

MODEL_ID = "black-forest-labs/FLUX.2-klein-4B"
MODEL_REVISION = "e7b7dc27f91deacad38e78976d1f2b499d76a294"
MODEL_LICENSE = "Apache-2.0"
FLUX_DIR = os.path.join(REPO_ROOT, ".cache", "flux")
MODEL_DIR = os.path.join(FLUX_DIR, "models", "FLUX.2-klein-4B")
CONCEPT_DIR = os.path.join(FLUX_DIR, "concepts")
STATUS_PATH = os.path.join(FLUX_DIR, "status.json")
FAILURES_PATH = os.path.join(FLUX_DIR, "failures.jsonl")
# Distilled model: the model card's settings (4 steps, guidance 1.0).
STEPS = 4
GUIDANCE = 1.0
WATCH_INTERVAL_S = 300
STRUCTURE_EVERY = 25          # structure finished concepts after this many new jobs
V2_SPEC = inventory.SPEC_PATH


def concept_paths(job) -> tuple:
    base = os.path.join(CONCEPT_DIR, job.creative_id, job.part)
    return base + ".png", base + ".json"


def is_done(job) -> bool:
    png, sidecar = concept_paths(job)
    if not (os.path.exists(png) and os.path.exists(sidecar)):
        return False
    with open(sidecar, encoding="utf-8") as f:
        return json.load(f).get("prompt_sha256") == job.prompt_sha256


def _atomic_write(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def load_pipeline():
    import torch
    from diffusers import Flux2KleinPipeline, PipelineQuantizationConfig

    if not os.path.exists(os.path.join(MODEL_DIR, "model_index.json")):
        raise FileNotFoundError(f"Model not found at {MODEL_DIR}; run tools/asset_generation/setup_flux.sh")
    quant = PipelineQuantizationConfig(
        quant_backend="bitsandbytes_4bit",
        quant_kwargs={"load_in_4bit": True, "bnb_4bit_quant_type": "nf4", "bnb_4bit_compute_dtype": torch.bfloat16},
        components_to_quantize=["transformer", "text_encoder"],
    )
    pipe = Flux2KleinPipeline.from_pretrained(MODEL_DIR, torch_dtype=torch.bfloat16, quantization_config=quant)
    pipe.enable_model_cpu_offload()
    pipe.set_progress_bar_config(disable=True)
    return pipe


def environment() -> dict:
    import bitsandbytes
    import diffusers
    import torch
    import transformers
    return {"torch": torch.__version__, "cuda": torch.version.cuda, "diffusers": diffusers.__version__,
            "transformers": transformers.__version__, "bitsandbytes": bitsandbytes.__version__,
            "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None}


def generate(pipe, job, env: dict) -> dict:
    import io
    import torch

    started = time.monotonic()
    image = pipe(prompt=job.prompt, width=job.width, height=job.height, num_inference_steps=STEPS,
                 guidance_scale=GUIDANCE, generator=torch.Generator(device="cpu").manual_seed(job.seed)).images[0]
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    data = buf.getvalue()
    png, sidecar = concept_paths(job)
    _atomic_write(png, data)
    record = dict(job.as_dict(), model=MODEL_ID, model_revision=MODEL_REVISION, model_license=MODEL_LICENSE,
                  steps=STEPS, guidance_scale=GUIDANCE, quantization="bitsandbytes nf4 (transformer, text_encoder)",
                  generator="torch.Generator(cpu).manual_seed(seed)", environment=env,
                  image_sha256=hashlib.sha256(data).hexdigest(), seconds=round(time.monotonic() - started, 2),
                  generated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  clean_room={"image_inputs": None, "proprietary_references": False})
    _atomic_write(sidecar, (json.dumps(record, indent=2, sort_keys=True) + "\n").encode())
    return record


def write_status(**fields) -> None:
    fields["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _atomic_write(STATUS_PATH, (json.dumps(fields, indent=2) + "\n").encode())


def current_jobs(only_families=None) -> list:
    jobs = flux_jobs.plan_jobs(inventory.build_plan(inventory.load_spec()))
    return [job for job in jobs if not only_families or job.family in only_families]


def run_pass(pipe, env, only_families=None, limit=None) -> tuple:
    jobs = current_jobs(only_families)
    pending = [job for job in jobs if not is_done(job)]
    if limit:
        pending = pending[:limit]
    done_before = len(jobs) - len([j for j in jobs if not is_done(j)])
    failures, times = 0, []
    for index, job in enumerate(pending, 1):
        write_status(state="generating", total_jobs=len(jobs), done=done_before + index - 1 - failures,
                     failures_this_pass=failures, current=job.job_id,
                     avg_seconds=round(sum(times) / len(times), 2) if times else None)
        try:
            record = generate(pipe, job, env)
            times.append(record["seconds"])
            print(f"[{done_before + index}/{len(jobs)}] {job.job_id} {record['seconds']}s", flush=True)
        except Exception as exc:  # recorded and surfaced in status; the pass continues with other jobs
            failures += 1
            with open(FAILURES_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps({"job_id": job.job_id, "error": repr(exc), "traceback": traceback.format_exc(),
                                    "at": datetime.datetime.now(datetime.timezone.utc).isoformat()}) + "\n")
            print(f"FAILED {job.job_id}: {exc!r}", file=sys.stderr, flush=True)
            if "out of memory" in str(exc).lower():
                import torch
                torch.cuda.empty_cache()
            continue
        if len(times) % STRUCTURE_EVERY == 0:
            try:
                structure()
            except Exception as exc:  # a structuring bug must not stop concept generation; it is logged
                with open(FAILURES_PATH, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"job_id": "structure", "error": repr(exc), "traceback": traceback.format_exc(),
                                        "at": datetime.datetime.now(datetime.timezone.utc).isoformat()}) + "\n")
                print(f"STRUCTURE FAILED: {exc!r}", file=sys.stderr, flush=True)
    remaining = len([j for j in jobs if not is_done(j)])
    write_status(state="idle" if remaining == 0 else "pass-complete", total_jobs=len(jobs), done=len(jobs) - remaining,
                 failures_this_pass=failures, current=None,
                 avg_seconds=round(sum(times) / len(times), 2) if times else None)
    return len(jobs), remaining, failures


def structure() -> dict:
    """Structures every render key whose concepts are complete (tools/asset_generation/flux_structure.py)."""
    from asset_generation import flux_structure  # imported late: it imports this module
    counts = flux_structure.structure_all()
    print(f"Structured: {json.dumps(counts)}", flush=True)
    return counts


def build_packs() -> None:
    """Rebuilds and verifies the v2 full-inventory packs with the system Python (standard library + ffmpeg)."""
    import subprocess
    script = os.path.join(TOOLS_DIR, "asset_generation", "generate_full_inventory.py")
    for action in ("--write", "--check"):
        result = subprocess.run(["python3", script, action, "--spec", V2_SPEC], capture_output=True, text=True)
        tail = (result.stdout + result.stderr).strip().splitlines()[-1:] or [""]
        print(f"Packs {action}: exit {result.returncode}: {tail[0]}", flush=True)
        if result.returncode != 0:
            with open(FAILURES_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps({"job_id": f"packs{action}", "error": result.stderr[-4000:],
                                    "at": datetime.datetime.now(datetime.timezone.utc).isoformat()}) + "\n")
            return


def main():
    parser = argparse.ArgumentParser(description="Generate FLUX.2 concepts for every inventoried visual")
    parser.add_argument("--watch", action="store_true", help="keep running and re-plan every few minutes")
    parser.add_argument("--family", action="append", help="only these families (repeatable)")
    parser.add_argument("--limit", type=int, help="generate at most N pending jobs per pass")
    parser.add_argument("--plan", action="store_true", help="print job counts and exit (no model load)")
    args = parser.parse_args()

    if args.plan:
        jobs = current_jobs(args.family)
        done = sum(is_done(job) for job in jobs)
        print(json.dumps({"jobs": len(jobs), "done": done, "pending": len(jobs) - done}, indent=2))
        return
    pipe = load_pipeline()
    env = environment()
    while True:
        total, remaining, failures = run_pass(pipe, env, args.family, args.limit)
        print(f"Pass complete: {total - remaining}/{total} done, {remaining} pending, {failures} failed this pass", flush=True)
        if args.watch and not args.family and not args.limit:
            structure()
            build_packs()
        if not args.watch:
            sys.exit(1 if failures else 0)
        time.sleep(WATCH_INTERVAL_S)


if __name__ == "__main__":
    main()
