"""Manifest builder — provenance for one benchmark cell.

A manifest is the join key between `metrics.json` (correctness — from compbench)
and `duct-*.jsonl` (cost — from con-duct). It captures enough for a report
aggregator to reconstruct the exact run without needing the original inputs.
"""

from __future__ import annotations

import hashlib
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from compbench import __version__ as compbench_version

_DIGEST_CHUNK_BYTES = 64 * 1024 * 1024


def input_digest(data: bytes) -> str:
    """SHA-256 hex digest of arbitrary bytes."""
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def array_digest(arr: np.ndarray) -> str:
    """Canonical SHA-256 over shape + dtype + bytes.

    ``sha256(arr.tobytes())`` alone collides for two arrays with identical
    byte content but different shape/dtype (e.g. a (100,4) int16 reshape of
    a (200,2) int16). The manifest is a join key across cells, so the digest
    must distinguish them.
    """
    h = hashlib.sha256()
    h.update(f"shape={tuple(arr.shape)}|dtype={arr.dtype.str}|".encode())
    # Feed the hash in slices rather than via one `tobytes()`. `tobytes()`
    # copies the entire array into a fresh bytes object — a second 27 GB
    # allocation on the paper's full-length recordings, for a digest we
    # could just as well stream (plan §Phase 3.5 [R5-H2]).
    contiguous = np.ascontiguousarray(arr)
    flat = contiguous.reshape(-1)
    itemsize = max(int(flat.dtype.itemsize), 1)
    step = max(1, _DIGEST_CHUNK_BYTES // itemsize)
    for start in range(0, flat.size, step):
        h.update(flat[start : start + step].tobytes())
    return h.hexdigest()


def git_sha(repo: Path | None = None) -> str | None:
    """Current HEAD SHA of the compbench repo, or None if not under git."""
    cwd = repo or Path(__file__).resolve().parent
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
        return out.strip() or None
    except (subprocess.SubprocessError, FileNotFoundError):
        return None


def build_manifest(
    dataset_provenance: dict[str, Any],
    codec_description: dict[str, Any],
    input_array: np.ndarray,
    sample_rate_hz: float,
    duration_s: float,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble a manifest dictionary. Callers write it to `manifest.json`.

    `input_array` is the (n_samples, n_channels) benchmark input; its shape,
    dtype and bytes go into the digest so join keys never collide between
    two runs with the same raw byte content but different reshapes.
    """
    manifest = {
        "compbench_version": compbench_version,
        "git_sha": git_sha(),
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "python": {
            "version": sys.version.split()[0],
            "impl": platform.python_implementation(),
        },
        "platform": {
            "system": platform.system(),
            "machine": platform.machine(),
            "release": platform.release(),
        },
        "input": {
            "sample_rate_hz": sample_rate_hz,
            "duration_s": duration_s,
            "n_channels": int(input_array.shape[1]) if input_array.ndim > 1 else 1,
            "shape": list(input_array.shape),
            "dtype": str(input_array.dtype),
            "nbytes": int(input_array.nbytes),
            "sha256": array_digest(input_array),
            "provenance": dataset_provenance,
        },
        "codec": codec_description,
    }
    if extra:
        manifest["extra"] = extra
    return manifest
