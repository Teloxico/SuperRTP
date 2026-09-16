#!/usr/bin/env bash
set -euo pipefail

PINNED_TAG="v3.717"
PINNED_COMMIT="e733f289def676f06db8121bbdb4386cc8f634f5"
ARCHIVE_SHA256="d73c524a186eeb9e4b6c4b6e2350c3f2449c05ce9a94b3edeebeff18c3ec842d"
GAME_EXE_SHA256="91821bd2439f562811060904498086709b8ac603640551e4f2fca45a0ff5f999"
UPSTREAM_URL="https://github.com/smokingwolf/tool_wolf_rpg_editor/releases/download/v3.717/WolfRPGEditor_3.717_mini.zip"

INSTALL_DIR="${HOME}/.local/share/wolf-3.717"
GAME_EXE="${INSTALL_DIR}/Game.exe"
BUILD_META_FILE="${INSTALL_DIR}/wolf.build.json"
mkdir -p "${INSTALL_DIR}"

write_build_metadata() {
  cat <<EOF > "${BUILD_META_FILE}"
{
  "runtime": "wolf-rpg-editor",
  "version": "3.717",
  "pinned_tag": "${PINNED_TAG}",
  "upstream_commit": "${PINNED_COMMIT}",
  "upstream_repo": "https://github.com/smokingwolf/tool_wolf_rpg_editor",
  "archive_sha256": "${ARCHIVE_SHA256}",
  "game_exe_sha256": "${GAME_EXE_SHA256}",
  "workdir_current": true,
  "static_executable": false,
  "build_config_revision": "wolfcfg1"
}
EOF
  echo "Emitted build metadata to ${BUILD_META_FILE}"
}

if [[ -f "${GAME_EXE}" ]]; then
  echo "Found existing Game.exe at ${GAME_EXE}, checking SHA-256..."
  CURRENT_SHA=$(sha256sum "${GAME_EXE}" | cut -d' ' -f1)
  if [[ "${CURRENT_SHA}" == "${GAME_EXE_SHA256}" ]]; then
    echo "Game.exe matches pinned checksum ${GAME_EXE_SHA256}."
    if [[ ! -f "${BUILD_META_FILE}" ]]; then
      write_build_metadata
    fi
    exit 0
  else
    echo "Existing Game.exe checksum mismatch: got ${CURRENT_SHA}, expected ${GAME_EXE_SHA256}. Reinstalling..."
  fi
fi

TEMP_ZIP="/tmp/WolfRPGEditor_3.717_mini.zip"
if [[ -f "${TEMP_ZIP}" ]]; then
  echo "Found existing download at ${TEMP_ZIP}, checking SHA-256..."
  LOCAL_ZIP_SHA=$(sha256sum "${TEMP_ZIP}" | cut -d' ' -f1)
  if [[ "${LOCAL_ZIP_SHA}" != "${ARCHIVE_SHA256}" ]]; then
    echo "Checksum mismatch for local zip, redownloading..."
    rm -f "${TEMP_ZIP}"
  fi
fi

if [[ ! -f "${TEMP_ZIP}" ]]; then
  echo "Downloading WOLF RPG Editor v3.717 mini archive from upstream release..."
  curl -L --retry 3 -o "${TEMP_ZIP}" "${UPSTREAM_URL}"
fi

ACTUAL_ZIP_SHA=$(sha256sum "${TEMP_ZIP}" | cut -d' ' -f1)
if [[ "${ACTUAL_ZIP_SHA}" != "${ARCHIVE_SHA256}" ]]; then
  echo "CRITICAL: Archive checksum validation failed!"
  echo "Expected: ${ARCHIVE_SHA256}"
  echo "Actual:   ${ACTUAL_ZIP_SHA}"
  exit 1
fi
echo "Archive checksum verified: ${ACTUAL_ZIP_SHA}"

echo "Extracting Game.exe..."
python3 -c "
import zipfile
with zipfile.ZipFile('${TEMP_ZIP}', 'r') as z:
    z.extract('Game.exe', '${INSTALL_DIR}')
"

ACTUAL_EXE_SHA=$(sha256sum "${GAME_EXE}" | cut -d' ' -f1)
if [[ "${ACTUAL_EXE_SHA}" != "${GAME_EXE_SHA256}" ]]; then
  echo "CRITICAL: Game.exe checksum validation failed!"
  echo "Expected: ${GAME_EXE_SHA256}"
  echo "Actual:   ${ACTUAL_EXE_SHA}"
  exit 1
fi
echo "Game.exe checksum verified: ${ACTUAL_EXE_SHA}"

chmod +x "${GAME_EXE}"
write_build_metadata
echo "WOLF RPG Editor v3.717 runtime installed successfully to ${INSTALL_DIR}"
