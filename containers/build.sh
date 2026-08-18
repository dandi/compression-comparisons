#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Yaroslav Halchenko <yaroslav.o.halchenko@dartmouth.edu>
# SPDX-License-Identifier: MIT
#
# Generated with Claude Code 2.1.234 / Claude Opus 4.7 (1M context)
#
# Build all three compbench images with podman (or docker, per CONTAINER_ENGINE).
#
# Usage:
#   ./containers/build.sh                    # podman, all three
#   CONTAINER_ENGINE=docker ./containers/build.sh
#   IMAGES=compbench-base ./containers/build.sh   # only the named one(s)

set -euo pipefail

ENGINE="${CONTAINER_ENGINE:-podman}"
TAG="${TAG:-local}"
IMAGES="${IMAGES:-compbench-base compbench-ks25 compbench-ks4}"

if ! command -v "$ENGINE" >/dev/null 2>&1; then
    echo "ERROR: $ENGINE not on PATH. Set CONTAINER_ENGINE=docker or install $ENGINE." >&2
    exit 1
fi

repo_root="$(cd "$(dirname "$0")/.." && pwd)"

for image in $IMAGES; do
    dockerfile="$repo_root/containers/${image}.Dockerfile"
    if [[ ! -f "$dockerfile" ]]; then
        echo "ERROR: no Dockerfile for $image at $dockerfile" >&2
        exit 1
    fi
    echo ">>> Building ${image}:${TAG} via $ENGINE"
    "$ENGINE" build -t "${image}:${TAG}" -f "$dockerfile" "$repo_root"
done

echo ">>> All done."
