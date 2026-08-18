"""Loader for a plain numpy .npy file.

Provenance is minimal — a path + a sample-rate the caller supplies (or the
default of 30 000 Hz for ephys).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from compbench.datasets import register
from compbench.datasets.base import LoadedDataset


@register("npy")
def load_npy(
    path: str | Path,
    sample_rate_hz: float | str = 30_000.0,
) -> LoadedDataset:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f".npy input not found: {p}")
    arr = np.load(p)
    if arr.ndim == 1:
        arr = arr[:, None]
    if arr.ndim != 2:
        raise ValueError(f"Expected 1D or 2D .npy, got shape {arr.shape}")
    return LoadedDataset(
        data=arr,
        sample_rate_hz=float(sample_rate_hz),
        provenance={"loader": "npy", "params": {"path": str(p)}},
    )
