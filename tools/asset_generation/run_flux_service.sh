#!/usr/bin/env bash
# Runs FLUX asset generation to completion under a systemd user service, so it survives
# crashes, logouts of this session and reboots without supervision.
#
#   tools/asset_generation/run_flux_service.sh --install   # install, enable and start the service
#   systemctl --user status superrtp-flux                  # check it
#   tail -f .cache/flux/worker.log                         # follow progress (.cache/flux/status.json)
#
# The service runs flux_worker.py --until-complete: generate every concept, structure,
# build and verify the packs, then free the model (~12 GB) and write
# .cache/flux/COMPLETE.json. After that this script disables the service. To regenerate
# later (e.g. after editing the art direction), delete COMPLETE.json, run
# tools/asset_generation/setup_flux.sh, then --install again.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
UNIT="superrtp-flux.service"
UNIT_PATH="${HOME}/.config/systemd/user/${UNIT}"
COMPLETE="${REPO_ROOT}/.cache/flux/COMPLETE.json"
LOG="${REPO_ROOT}/.cache/flux/worker.log"

if [[ "${1:-}" == "--install" ]]; then
  mkdir -p "$(dirname "${UNIT_PATH}")"
  cat > "${UNIT_PATH}" <<EOF
[Unit]
Description=SuperRTP FLUX.2 asset generation (runs to completion)
StartLimitIntervalSec=3600
StartLimitBurst=5

[Service]
Type=simple
WorkingDirectory=${REPO_ROOT}
ExecStart=${REPO_ROOT}/tools/asset_generation/run_flux_service.sh
Restart=on-failure
RestartSec=120
StandardOutput=append:${LOG}
StandardError=append:${LOG}

[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload
  systemctl --user enable --now "${UNIT}"
  echo "Installed and started ${UNIT_PATH}"
  exit 0
fi

cd "${REPO_ROOT}"
if [[ -f "${COMPLETE}" ]]; then
  echo "Generation already complete (${COMPLETE}); disabling ${UNIT}."
  systemctl --user disable "${UNIT}"
  exit 0
fi
.cache/flux/venv/bin/python -u tools/asset_generation/flux_worker.py --until-complete
if [[ -f "${COMPLETE}" ]]; then
  echo "Generation complete; disabling ${UNIT}."
  systemctl --user disable "${UNIT}"
fi
