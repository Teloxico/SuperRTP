#!/usr/bin/env python3
"""
Replaces the downloaded bf16 FLUX.2 [klein] 4B transformer and text encoder with the
4-bit NF4 weights the worker actually runs, saving ~10 GB of disk.

Safety: the swap happens only if a reference job renders byte-identically from the
saved 4-bit weights and from the original bf16 weights (both quantized the same way).
The originals can always be re-downloaded with tools/asset_generation/setup_flux.sh.

    .cache/flux/venv/bin/python tools/asset_generation/flux_compact_model.py
"""

import gc
import hashlib
import io
import os
import shutil
import sys

TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS_DIR)

from asset_generation import flux_worker  # noqa: E402

COMPONENTS = ("transformer", "text_encoder")


def render(pipe, job) -> str:
    import torch
    image = pipe(prompt=job.prompt, width=job.width, height=job.height, num_inference_steps=flux_worker.STEPS,
                 guidance_scale=flux_worker.GUIDANCE, generator=torch.Generator(device="cpu").manual_seed(job.seed)).images[0]
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return hashlib.sha256(buf.getvalue()).hexdigest()


def main():
    import torch
    model_dir = flux_worker.MODEL_DIR
    if flux_worker.is_compacted():
        print("Model already compacted")
        return
    job = flux_worker.current_jobs()[0]
    pipe = flux_worker.load_pipeline()
    reference = render(pipe, job)
    staged = {}
    for name in COMPONENTS:
        staged[name] = os.path.join(model_dir, f"{name}-nf4.staging")
        shutil.rmtree(staged[name], ignore_errors=True)
        getattr(pipe, name).save_pretrained(staged[name])
    del pipe
    gc.collect()
    torch.cuda.empty_cache()

    pipe = flux_worker.load_pipeline(prequantized_dirs=staged)
    candidate = render(pipe, job)
    del pipe
    gc.collect()
    print(f"reference {reference}\ncandidate {candidate}")
    if candidate != reference:
        for path in staged.values():
            shutil.rmtree(path)
        sys.exit("4-bit weights do not reproduce the reference render; originals kept")
    for name in COMPONENTS:
        shutil.rmtree(os.path.join(model_dir, name))
        os.replace(staged[name], os.path.join(model_dir, f"{name}-nf4"))
    print("Compacted: bf16 transformer and text encoder replaced by verified NF4 weights")


if __name__ == "__main__":
    main()
