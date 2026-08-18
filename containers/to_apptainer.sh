#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Yaroslav Halchenko <yaroslav.o.halchenko@dartmouth.edu>
# SPDX-License-Identifier: MIT
#
# Generated with Claude Code 2.1.234 / Claude Opus 4.7 (1M context)
#
# Convert a locally-built OCI image (from podman/docker) into a `.sif` file
# consumable by apptainer/singularity on HPC.
#
# Usage:
#   ./containers/to_apptainer.sh compbench-base:local
#   ./containers/to_apptainer.sh compbench-base:local /shared/images/  # custom dest

set -euo pipefail

image="${1:?usage: $0 <image:tag> [dest_dir]}"
dest="${2:-.}"
name="${image%%:*}"

for tool in apptainer singularity; do
    if command -v "$tool" >/dev/null 2>&1; then
        APPTAINER="$tool"
        break
    fi
done
: "${APPTAINER:?apptainer or singularity required}"

sif="${dest%/}/${name}.sif"

if command -v podman >/dev/null 2>&1; then
    echo ">>> Piping podman → $APPTAINER via oci-archive"
    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' EXIT
    podman save --format oci-archive -o "$tmp/img.tar" "$image"
    "$APPTAINER" build "$sif" "oci-archive:$tmp/img.tar"
elif command -v docker >/dev/null 2>&1; then
    echo ">>> Piping docker → $APPTAINER via docker-daemon"
    "$APPTAINER" build "$sif" "docker-daemon://$image"
else
    echo "ERROR: need podman or docker to source the OCI image; neither found." >&2
    exit 1
fi

echo ">>> Built: $sif"
