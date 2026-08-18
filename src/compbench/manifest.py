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

from compbench import __version__ as compbench_version


def input_digest(data: bytes) -> str:
    """SHA-256 hex digest of arbitrary bytes."""
    h = hashlib.sha256()
    h.update(data)
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
    input_bytes: bytes,
    sample_rate_hz: float,
    duration_s: float,
    n_channels: int,
    dtype: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble a manifest dictionary. Callers write it to `manifest.json`."""
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
            "n_channels": n_channels,
            "dtype": dtype,
            "nbytes": len(input_bytes),
            "sha256": input_digest(input_bytes),
            "provenance": dataset_provenance,
        },
        "codec": codec_description,
    }
    if extra:
        manifest["extra"] = extra
    return manifest
