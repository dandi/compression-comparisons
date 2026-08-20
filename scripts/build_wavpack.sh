#!/usr/bin/env bash
# Build WavPack from source into vendor/wavpack/.
#
# WHY THIS EXISTS
# ---------------
# `wavpack-numcodecs` wraps libwavpack. Its setup.py takes one of two paths:
#
#   if shutil.which("wavpack") is not None:   -> link against the SYSTEM library
#   else:                                     -> use shipped prebuilt libs,
#                                                which require the running
#                                                glibc to be EXACTLY one of
#                                                the versions it ships
#
# The shipped builds are glibc 2.35 and 2.39 only. Every host this project has
# touched misses: the first deploy image was 2.36, the GPU image is 2.41, and
# even AIND's own `aind-ephys-pipeline-base` is 2.31 — so the container is not
# a way around this, contrary to what containers/README implied.
#
# Putting a `wavpack` binary on PATH takes the first branch and the glibc check
# never runs. That is all this script does.
#
# Prefer the distro package when it is available:
#     sudo apt-get install -y wavpack libwavpack-dev
# This script is the no-root fallback.
#
# Usage:  scripts/build_wavpack.sh [version]
set -euo pipefail

VERSION="${1:-5.8.1}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PREFIX="$REPO_ROOT/vendor/wavpack"
BUILD="$REPO_ROOT/.tmp/wavpack-build"

if [ -x "$PREFIX/bin/wavpack" ]; then
    echo "WavPack already built: $("$PREFIX/bin/wavpack" --version 2>&1 | head -1)"
    echo "  prefix: $PREFIX"
    exit 0
fi

mkdir -p "$BUILD" && cd "$BUILD"
tarball="wavpack-${VERSION}.tar.xz"
[ -f "$tarball" ] || curl -fsSLO "https://www.wavpack.com/${tarball}"
rm -rf "wavpack-${VERSION}"
tar xf "$tarball"
cd "wavpack-${VERSION}"
./configure --prefix="$PREFIX" >configure.log 2>&1
make -j"$(nproc)" >build.log 2>&1
make install >install.log 2>&1

echo "Built $("$PREFIX/bin/wavpack" --version 2>&1 | head -1) -> $PREFIX"
echo
echo "Now install the codec with the binary on PATH:"
echo "    export PATH=\"$PREFIX/bin:\$PATH\""
echo "    export LD_LIBRARY_PATH=\"$PREFIX/lib:\$LD_LIBRARY_PATH\""
echo "    uv pip install --python .venv/bin/python wavpack-numcodecs"
echo
echo "Both paths are exported for you by \`make\` and the Snakefile (see .env)."
