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

A job is redone only when its prompt, size or seed changes (prompt_sha256), or, for a
side or back view, when the front view it was conditioned on changed. With
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


def _sidecar(job) -> dict:
    png, sidecar = concept_paths(job)
    if not (os.path.exists(png) and os.path.exists(sidecar)):
        return None
    with open(sidecar, encoding="utf-8") as f:
        return json.load(f)


def reference_job(job):
    """The front-view job a side or back view is conditioned on (same creative, same character)."""
    creative_id, part = job.reference.split("/", 1)
    return flux_jobs.FluxJob(job.reference, creative_id, job.family, part, "", 0, 0, 0)


def is_done(job) -> bool:
    record = _sidecar(job)
    if not record or record.get("prompt_sha256") != job.prompt_sha256:
        return False
    if job.reference:
        front = _sidecar(reference_job(job))
        inputs = record.get("clean_room", {}).get("image_inputs") or []
        return bool(front) and [i.get("image_sha256") for i in inputs] == [front["image_sha256"]]
    return True


def _atomic_write(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def is_compacted() -> bool:
    """True once flux_compact_model.py has replaced the bf16 weights with verified NF4 weights."""
    return all(os.path.isdir(os.path.join(MODEL_DIR, f"{name}-nf4")) for name in ("transformer", "text_encoder"))


def load_pipeline(prequantized_dirs: dict = None):
    """Loads the pipeline with the transformer and text encoder in 4-bit NF4: quantized on load from
    the bf16 download, or read from saved NF4 weights (`prequantized_dirs`, or the compacted model)."""
    import torch
    from diffusers import Flux2KleinPipeline, Flux2Transformer2DModel, PipelineQuantizationConfig
    from transformers import Qwen3ForCausalLM

    if not os.path.exists(os.path.join(MODEL_DIR, "model_index.json")):
        raise FileNotFoundError(f"Model not found at {MODEL_DIR}; run tools/asset_generation/setup_flux.sh")
    if prequantized_dirs is None and is_compacted():
        prequantized_dirs = {name: os.path.join(MODEL_DIR, f"{name}-nf4") for name in ("transformer", "text_encoder")}
    if prequantized_dirs:
        transformer = Flux2Transformer2DModel.from_pretrained(prequantized_dirs["transformer"], torch_dtype=torch.bfloat16)
        text_encoder = Qwen3ForCausalLM.from_pretrained(prequantized_dirs["text_encoder"], dtype=torch.bfloat16)
        pipe = Flux2KleinPipeline.from_pretrained(MODEL_DIR, transformer=transformer, text_encoder=text_encoder,
                                                  torch_dtype=torch.bfloat16)
    else:
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


VIEW_ATTEMPTS = 4             # seeds tried per turnaround view before keeping the best-scoring one
RETRY_SEED_STEP = 7919


def generate(pipe, job, env: dict) -> dict:
    """Renders one job. Turnaround views are checked (flux_structure.view_check) and re-rendered with
    other seeds when they fail; if every attempt fails, the best one is kept and its record says so."""
    import io
    import torch
    from PIL import Image
    from asset_generation import flux_structure  # imported late: it imports this module

    started = time.monotonic()
    image_inputs, reference_image, front_scores = None, None, None
    if job.reference:
        front = reference_job(job)
        front_record = _sidecar(front)
        if not front_record:
            raise FileNotFoundError(f"{job.job_id} needs its front view {job.reference}, which is not generated")
        reference_image = Image.open(concept_paths(front)[0]).convert("RGB")
        image_inputs = [{"job_id": job.reference, "image_sha256": front_record["image_sha256"],
                         "origin": "generated by this worker for the same character"}]
        front_scores = (front_record.get("view_check") or {}).get("scores")
    attempts = []
    for attempt in range(VIEW_ATTEMPTS if job.view else 1):
        seed = job.seed + attempt * RETRY_SEED_STEP
        image = pipe(prompt=job.prompt, image=[reference_image] if reference_image else None, width=job.width,
                     height=job.height, num_inference_steps=STEPS, guidance_scale=GUIDANCE,
                     generator=torch.Generator(device="cpu").manual_seed(seed)).images[0]
        check = flux_structure.view_check(image, job.key_rgb, job.view, job.view_kind, front_scores) if job.view else None
        attempts.append((seed, image, check))
        if check is None or check["passed"]:
            break
    seed, image, check = attempts[-1] if attempts[-1][2] is None or attempts[-1][2]["passed"] else \
        max(attempts, key=lambda a: a[2]["quality"])
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    data = buf.getvalue()
    png, sidecar = concept_paths(job)
    _atomic_write(png, data)
    record = dict(job.as_dict(), model=MODEL_ID, model_revision=MODEL_REVISION, model_license=MODEL_LICENSE,
                  steps=STEPS, guidance_scale=GUIDANCE, quantization="bitsandbytes nf4 (transformer, text_encoder)",
                  generator="torch.Generator(cpu).manual_seed(seed)", environment=env, used_seed=seed,
                  image_sha256=hashlib.sha256(data).hexdigest(), seconds=round(time.monotonic() - started, 2),
                  generated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  clean_room={"image_inputs": image_inputs, "proprietary_references": False})
    if check is not None:
        record["view_check"] = dict(check, attempts=len(attempts))
    _atomic_write(sidecar, (json.dumps(record, indent=2, sort_keys=True) + "\n").encode())
    return record


def reference_job_from(jobs, job):
    """The planned front-view job of a side or back view."""
    return next(j for j in jobs if j.job_id == job.reference)


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
        if job.reference and not is_done(reference_job_from(jobs, job)):
            failures += 1   # the front view failed this pass; the next pass retries both
            print(f"DEFERRED {job.job_id}: front view {job.reference} is not generated", file=sys.stderr, flush=True)
            continue
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


def build_packs() -> bool:
    """Rebuilds and verifies the v2 full-inventory packs with the system Python (standard library + ffmpeg).
    Returns True when both steps succeed."""
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
            return False
    return True


COMPLETE_PATH = os.path.join(FLUX_DIR, "COMPLETE.json")
MAX_PASSES = 3                # passes that retry failed jobs before giving up


def run_runtime_gate() -> dict:
    """Runs tools/verify_generated_packs.py (real EasyRPG and mkxp-z against the packs). Its
    outcome is recorded rather than retried: regenerating images cannot fix a failed gate."""
    import subprocess
    result = subprocess.run(["python3", os.path.join(TOOLS_DIR, "verify_generated_packs.py")], capture_output=True, text=True)
    lines = [l for l in result.stdout.splitlines() if l.startswith("[")]
    print("\n".join(lines) or result.stderr.strip()[-2000:], flush=True)
    return {"passed": result.returncode == 0, "report": "artifacts/generation/full-inventory/v2/runtime-gate.json",
            "summary": lines}


def finish(total: int, gate: dict) -> None:
    """Everything is generated, structured and packed: record completion and free the model and its
    environment (~12 GB), which setup_flux.sh can recreate. Concepts and structured images are kept."""
    record = {"completed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "jobs": total, "runtime_gate": gate,
              "model": MODEL_ID, "model_revision": MODEL_REVISION,
              "freed": [os.path.relpath(p, REPO_ROOT) for p in (MODEL_DIR, os.path.join(FLUX_DIR, "venv"))]}
    _atomic_write(COMPLETE_PATH, (json.dumps(record, indent=2) + "\n").encode())
    import shutil
    shutil.rmtree(MODEL_DIR)
    shutil.rmtree(os.path.join(FLUX_DIR, "venv"))   # this interpreter keeps running from memory
    print(f"Complete: {total} concepts generated and packed; freed {record['freed']}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Generate FLUX.2 concepts for every inventoried visual")
    parser.add_argument("--watch", action="store_true", help="keep running and re-plan every few minutes")
    parser.add_argument("--family", action="append", help="only these families (repeatable)")
    parser.add_argument("--limit", type=int, help="generate at most N pending jobs per pass")
    parser.add_argument("--plan", action="store_true", help="print job counts and exit (no model load)")
    parser.add_argument("--until-complete", action="store_true",
                        help="run passes until every job is done, structure, build and verify the packs, then "
                             "record completion and free the model (used by the systemd service)")
    args = parser.parse_args()

    if args.plan:
        jobs = current_jobs(args.family)
        done = sum(is_done(job) for job in jobs)
        print(json.dumps({"jobs": len(jobs), "done": done, "pending": len(jobs) - done}, indent=2))
        return
    pipe = load_pipeline()
    env = environment()
    if args.until_complete:
        for attempt in range(1, MAX_PASSES + 1):
            total, remaining, failures = run_pass(pipe, env)
            print(f"Pass {attempt}: {total - remaining}/{total} done, {remaining} pending, {failures} failed", flush=True)
            if remaining == 0:
                break
        if remaining:
            sys.exit(f"{remaining} jobs still failing after {MAX_PASSES} passes; see {FAILURES_PATH}")
        counts = structure()
        if counts["failed"] or counts["waiting_for_concepts"]:
            sys.exit(f"Structuring incomplete: {counts}")
        if not build_packs():
            sys.exit(f"Pack build or verification failed; see {FAILURES_PATH}")
        del pipe
        finish(total, run_runtime_gate())
        return
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
