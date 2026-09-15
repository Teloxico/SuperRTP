#!/usr/bin/env bash
set -euo pipefail

PINNED_COMMIT="826929eeb3ebc4b887c011604919217a790770f4"
INSTALL_DIR="${HOME}/.local/bin"
MKXP_BIN="${INSTALL_DIR}/mkxp-z"

mkdir -p "${INSTALL_DIR}"

if [[ -x "${MKXP_BIN}" ]]; then
  echo "Found existing mkxp-z at ${MKXP_BIN}, checking commit pin..."
  if strings "${MKXP_BIN}" | grep "826929e" >/dev/null 2>&1; then
    echo "mkxp-z matches pinned commit 826929e. Using cached binary."
    exit 0
  else
    echo "mkxp-z binary does not match pinned commit. Rebuilding..."
  fi
fi

echo "Installing mkxp-z build dependencies..."
if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y --no-install-recommends \
    meson ninja-build xxd \
    libsdl2-dev libsdl2-image-dev libsdl2-ttf-dev \
    libopenal-dev libvorbis-dev libogg-dev libphysfs-dev libtheora-dev \
    ruby-dev
fi

BUILD_DIR=$(mktemp -d /tmp/mkxp-z-build-XXXXXX)
trap 'rm -rf "${BUILD_DIR}"' EXIT

echo "Cloning mkxp-z repository..."
git clone https://github.com/mkxp-z/mkxp-z.git "${BUILD_DIR}"
cd "${BUILD_DIR}"
git checkout "${PINNED_COMMIT}"

echo "Configuring mkxp-z with meson..."
meson setup build \
  -Dworkdir_current=true \
  -Dstatic_executable=false \
  -Dmri_version=3.3 \
  -Dshared_fluid=false \
  -Dcpp_args="-D_TTF_Font=TTF_Font" \
  -Dcpp_link_args="['-ltheoradec']"

echo "Compiling mkxp-z..."
ninja -C build

if [[ -f "build/mkxp-z.x86_64" ]]; then
  cp "build/mkxp-z.x86_64" "${MKXP_BIN}"
elif [[ -f "build/mkxp-z" ]]; then
  cp "build/mkxp-z" "${MKXP_BIN}"
else
  echo "Error: compiled mkxp-z binary not found in build directory" >&2
  exit 1
fi

chmod +x "${MKXP_BIN}"
echo "Successfully installed mkxp-z to ${MKXP_BIN}"
