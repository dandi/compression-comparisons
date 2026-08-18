"""Synthetic multichannel int16 waveform loader.

Deterministic given `seed`. Not a scientifically-meaningful signal — its role
is to exercise the pipeline in unit tests and CI smoke.
"""

from __future__ import annotations

import numpy as np

from compbench.datasets import register
from compbench.datasets.base import LoadedDataset


@register("synthetic")
def load_synthetic(
    duration_s: float | str = 1.0,
    sample_rate_hz: float | str = 1000.0,
    n_channels: int | str = 4,
    dtype: str = "int16",
    seed: int | str = 0,
) -> LoadedDataset:
    """Generate a deterministic multi-channel waveform.

    Signal per channel = 5 Hz sinusoid + Gaussian noise + per-channel DC offset.
    Scaled into int16 range comfortably.
    """
    duration_s = float(duration_s)
    sample_rate_hz = float(sample_rate_hz)
    n_channels = int(n_channels)
    seed = int(seed)

    if duration_s <= 0 or sample_rate_hz <= 0 or n_channels <= 0:
        raise ValueError("duration_s, sample_rate_hz, n_channels must all be positive")

    n_samples = round(duration_s * sample_rate_hz)
    rng = np.random.default_rng(seed)
    t = np.arange(n_samples, dtype=np.float64) / sample_rate_hz

    base = 1000.0 * np.sin(2 * np.pi * 5.0 * t)
    channels = np.empty((n_channels, n_samples), dtype=np.float64)
    for ch in range(n_channels):
        channels[ch] = base + 100.0 * rng.standard_normal(n_samples) + ch * 50.0

    data = channels.T.astype(np.dtype(dtype))
    return LoadedDataset(
        data=data,
        sample_rate_hz=sample_rate_hz,
        provenance={
            "loader": "synthetic",
            "params": {
                "duration_s": duration_s,
                "sample_rate_hz": sample_rate_hz,
                "n_channels": n_channels,
                "dtype": dtype,
                "seed": seed,
            },
        },
    )
