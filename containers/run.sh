#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Yaroslav Halchenko <yaroslav.o.halchenko@dartmouth.edu>
# SPDX-License-Identifier: MIT
#
# Generated with Claude Code 2.1.234 / Claude Opus 4.7 (1M context)
#
# Run a command inside one of the compbench images, using whichever container
# runtime is available. Repo root bind-mounted as /work (the process cwd).
#
# Priority: podman > docker > apptainer/singularity.
# Override with CONTAINER_ENGINE=<podman|docker|apptainer|singularity>.
#
# Usage:
#   ./containers/run.sh compbench-base:local compbench --version
#   ./containers/run.sh --gpu compbench-ks4:local nvidia-smi
#   CONTAINER_ENGINE=apptainer ./containers/run.sh compbench-base.sif compbench --help

set -euo pipefail

GPU_FLAG=0
if [[ "${1:-}" == "--gpu" ]]; then
    GPU_FLAG=1
    shift
fi

image="${1:?usage: $0 [--gpu] <image[:tag]|/path/to/img.sif> <cmd...>}"
shift

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
ENGINE="${CONTAINER_ENGINE:-}"

if [[ -z "$ENGINE" ]]; then
    for candidate in podman docker apptainer singularity; do
        if command -v "$candidate" >/dev/null 2>&1; then
            ENGINE="$candidate"
            break
        fi
    done
fi
: "${ENGINE:?no container runtime found — install podman, docker, or apptainer}"

case "$ENGINE" in
    podman|docker)
        args=(run --rm -v "$repo_root:/work" -w /work)
        if [[ "$GPU_FLAG" == 1 ]]; then
            args+=(--device nvidia.com/gpu=all)
        fi
        exec "$ENGINE" "${args[@]}" "$image" "$@"
        ;;
    apptainer|singularity)
        args=(exec --bind "$repo_root:/work" --pwd /work)
        if [[ "$GPU_FLAG" == 1 ]]; then
            args+=(--nv)
        fi
        exec "$ENGINE" "${args[@]}" "$image" "$@"
        ;;
    *)
        echo "ERROR: unrecognised CONTAINER_ENGINE=$ENGINE" >&2
        exit 1
        ;;
esac
