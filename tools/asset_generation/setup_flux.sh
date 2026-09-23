#!/usr/bin/env bash
# Sets up the local FLUX.2 [klein] 4B generation environment under .cache/flux/
# (git-ignored): a Python 3.12 virtualenv with pinned CUDA PyTorch and diffusers, and
# the pinned model revision (~16 GB; the duplicate single-file checkpoint and sample
# images are skipped). Needs `uv` and an NVIDIA GPU with a CUDA 12.8-capable driver.
# Nothing is installed outside the repository; no sudo.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FLUX_DIR="${REPO_ROOT}/.cache/flux"
VENV="${FLUX_DIR}/venv"
PY="${VENV}/bin/python"
MODEL_REVISION="e7b7dc27f91deacad38e78976d1f2b499d76a294"   # keep in sync with flux_worker.MODEL_REVISION

mkdir -p "${FLUX_DIR}"
[[ -x "${PY}" ]] || uv venv --python 3.12 "${VENV}"
uv pip install --python "${PY}" --index-url https://download.pytorch.org/whl/cu128 \
  --extra-index-url https://pypi.org/simple "torch==2.8.0"
uv pip install --python "${PY}" "diffusers==0.40.0" "transformers==5.17.0" "accelerate==1.15.0" \
  "safetensors==0.8.0" "bitsandbytes==0.50.2" "pillow==12.3.0" "numpy==2.5.3" \
  "huggingface-hub[hf_xet]==1.32.0" "scipy==1.17.1"

HF_HOME="${FLUX_DIR}/hf-home" "${VENV}/bin/hf" download black-forest-labs/FLUX.2-klein-4B \
  --revision "${MODEL_REVISION}" --local-dir "${FLUX_DIR}/models/FLUX.2-klein-4B" \
  --exclude "flux-2-klein-4b.safetensors" --exclude "*.jpg"

"${PY}" -c "import torch; assert torch.cuda.is_available(), 'CUDA not available'; print('FLUX environment ready on', torch.cuda.get_device_name(0))"
