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
    meson ninja-build xxd cmake \
    libsdl2-dev libsdl2-image-dev libsdl2-ttf-dev \
    libopenal-dev libvorbis-dev libogg-dev libphysfs-dev libtheora-dev \
    libpixman-1-dev libpng-dev zlib1g-dev libuchardet-dev libbz2-dev libfreetype-dev \
    ruby-dev
fi

# Ensure SDL2_sound is available (Homebrew or compile from source)
if command -v brew >/dev/null 2>&1; then
  echo "Checking Homebrew sdl2_sound..."
  if ! brew list sdl2_sound >/dev/null 2>&1; then
    brew install sdl2_sound || true
  fi
elif [[ -x "/home/linuxbrew/.linuxbrew/bin/brew" ]]; then
  eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"
  if ! brew list sdl2_sound >/dev/null 2>&1; then
    brew install sdl2_sound || true
  fi
fi

if ! pkg-config --exists SDL2_sound 2>/dev/null && ! [ -f /usr/local/lib/libSDL2_sound.so ] && ! [ -f /home/linuxbrew/.linuxbrew/lib/libSDL2_sound.so ]; then
  echo "Building SDL_sound v2.0.4 from source..."
  TMP_SDL_SOUND=$(mktemp -d /tmp/sdl-sound-build-XXXXXX)
  git clone --depth 1 -b v2.0.4 https://github.com/icculus/SDL_sound.git "${TMP_SDL_SOUND}"
  cmake -S "${TMP_SDL_SOUND}" -B "${TMP_SDL_SOUND}/build" \
    -DSDLSOUND_BUILD_TEST=OFF \
    -DSDLSOUND_BUILD_SHARED=ON \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX=/usr/local
  cmake --build "${TMP_SDL_SOUND}/build" -j"$(nproc)"
  if command -v sudo >/dev/null 2>&1; then
    sudo cmake --install "${TMP_SDL_SOUND}/build"
    sudo ldconfig || true
  else
    cmake --install "${TMP_SDL_SOUND}/build" --prefix "${HOME}/.local"
  fi
  rm -rf "${TMP_SDL_SOUND}"
fi

# Provide libiconv and libcharset archives on Linux (glibc provides iconv in libc)
if ! [ -f /usr/local/lib/libiconv.a ] && ! [ -f /usr/lib/libiconv.so ]; then
  echo "Creating iconv and charset static library archives for glibc compatibility..."
  if command -v sudo >/dev/null 2>&1; then
    sudo ar cr /usr/local/lib/libiconv.a
    sudo ar cr /usr/local/lib/libcharset.a
    sudo ldconfig || true
  else
    mkdir -p "${HOME}/.local/lib"
    ar cr "${HOME}/.local/lib/libiconv.a"
    ar cr "${HOME}/.local/lib/libcharset.a"
  fi
fi

EXTRA_LINK_ARGS="['-L/usr/local/lib', '-ltheoradec', '-Wl,-rpath,/usr/local/lib']"
if [[ -d "/home/linuxbrew/.linuxbrew/lib" ]]; then
  export PKG_CONFIG_PATH="/home/linuxbrew/.linuxbrew/lib/pkgconfig:/home/linuxbrew/.linuxbrew/opt/sdl2_sound/lib/pkgconfig:${PKG_CONFIG_PATH:-}"
  export LD_LIBRARY_PATH="/home/linuxbrew/.linuxbrew/lib:${LD_LIBRARY_PATH:-}"
  export LIBRARY_PATH="/home/linuxbrew/.linuxbrew/lib:${LIBRARY_PATH:-}"
  EXTRA_LINK_ARGS="['-L/usr/local/lib', '-ltheoradec', '-Wl,-rpath,/usr/local/lib', '-Wl,-rpath,/home/linuxbrew/.linuxbrew/lib', '-Wl,-rpath,/home/linuxbrew/.linuxbrew/opt/sdl2_sound/lib']"
fi
if [[ -d "/usr/local/lib" ]]; then
  export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:${PKG_CONFIG_PATH:-}"
  export LD_LIBRARY_PATH="/usr/local/lib:${LD_LIBRARY_PATH:-}"
  export LIBRARY_PATH="/usr/local/lib:${LIBRARY_PATH:-}"
fi

BUILD_DIR=$(mktemp -d /tmp/mkxp-z-build-XXXXXX)
trap 'rm -rf "${BUILD_DIR}"' EXIT

echo "Cloning mkxp-z repository..."
git clone https://github.com/mkxp-z/mkxp-z.git "${BUILD_DIR}"
cd "${BUILD_DIR}"
git checkout "${PINNED_COMMIT}"

echo "Detecting installed Ruby (MRI) version..."
MRI_VERSION=""
if command -v ruby >/dev/null 2>&1; then
  MRI_VERSION=$(ruby -e 'require "rbconfig"; puts "#{RbConfig::CONFIG[\"MAJOR\"]}.#{RbConfig::CONFIG[\"MINOR\"]}"' 2>/dev/null || true)
fi
if [[ -z "${MRI_VERSION}" ]]; then
  for candidate in $(pkg-config --list-all 2>/dev/null | grep -oE 'ruby-[0-9]+\.[0-9]+' | sort -uV); do
    ver="${candidate#ruby-}"
    if pkg-config --exists "ruby-${ver}" 2>/dev/null; then
      MRI_VERSION="${ver}"
    fi
  done
fi
if [[ -z "${MRI_VERSION}" ]]; then
  MRI_VERSION="3.2"
fi
echo "Using MRI version: ${MRI_VERSION}"

echo "Configuring mkxp-z with meson..."
meson setup build \
  -Dworkdir_current=true \
  -Dstatic_executable=false \
  -Dmri_version="${MRI_VERSION}" \
  -Dshared_fluid=false \
  -Dcpp_args="-D_TTF_Font=TTF_Font" \
  -Dcpp_link_args="${EXTRA_LINK_ARGS}"

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
