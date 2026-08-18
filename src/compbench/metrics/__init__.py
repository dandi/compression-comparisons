"""Correctness metrics: CR, RMSE, round-trip byte-equality, PRD/PRDN, latency."""

from __future__ import annotations

import time
from collections.abc import Callable

import numpy as np


def compression_ratio(original_bytes: int, encoded_bytes: int) -> float:
    """`original / encoded`. Undefined for empty input; returns 0.0."""
    if encoded_bytes <= 0:
        return 0.0
    return original_bytes / encoded_bytes


def rmse(original: np.ndarray, reconstructed: np.ndarray) -> float:
    """Root-mean-square error in the units of the input."""
    if original.shape != reconstructed.shape:
        raise ValueError(
            f"Shape mismatch: original {original.shape} vs reconstructed {reconstructed.shape}"
        )
    if original.dtype != reconstructed.dtype:
        # Coerce reconstructed to original dtype before diff to catch codec dtype bugs.
        reconstructed = reconstructed.astype(original.dtype)
    diff = original.astype(np.float64) - reconstructed.astype(np.float64)
    return float(np.sqrt(np.mean(diff * diff)))


def round_trip_ok(original: np.ndarray, reconstructed: np.ndarray) -> bool:
    """True iff shape, dtype, and every byte match exactly."""
    if original.shape != reconstructed.shape:
        return False
    if original.dtype != reconstructed.dtype:
        return False
    return bool(np.array_equal(original, reconstructed))


def prd(original: np.ndarray, reconstructed: np.ndarray) -> float:
    """Percent Root-mean-square Difference (PRD).

    Standard ECG distortion metric — required by T.261's ECG conformance
    testing. Defined as:

        PRD = 100 * sqrt( sum((x - x_hat)^2) / sum(x^2) )

    Units: percent. Lower is better; < 9 % is typically "very good" for ECG.
    """
    if original.shape != reconstructed.shape:
        raise ValueError("shape mismatch")
    x = original.astype(np.float64)
    xh = reconstructed.astype(np.float64)
    denom = float(np.sum(x * x))
    if denom == 0.0:
        return 0.0
    num = float(np.sum((x - xh) ** 2))
    return 100.0 * float(np.sqrt(num / denom))


def prdn(original: np.ndarray, reconstructed: np.ndarray) -> float:
    """Percent Root-mean-square Difference, Normalised (PRDN).

    Removes the mean before normalisation — insensitive to a constant offset,
    which matters for waveforms with a nonzero baseline (typical for ECG
    lead traces after AC coupling).

        PRDN = 100 * sqrt( sum((x - x_hat)^2) / sum((x - mean(x))^2) )
    """
    if original.shape != reconstructed.shape:
        raise ValueError("shape mismatch")
    x = original.astype(np.float64)
    xh = reconstructed.astype(np.float64)
    mean = float(np.mean(x))
    denom = float(np.sum((x - mean) ** 2))
    if denom == 0.0:
        return 0.0
    num = float(np.sum((x - xh) ** 2))
    return 100.0 * float(np.sqrt(num / denom))


def random_access_latency(
    fetch: Callable[[int, int], np.ndarray],
    n_samples: int,
    window_samples: int,
    n_probes: int = 32,
    seed: int = 0,
) -> dict[str, float]:
    """Measure random-access decode latency.

    Fires ``n_probes`` random windows of ``window_samples`` at ``fetch(start,
    length)`` and returns p50/p95/p99/mean of the wall-clock latency in
    seconds. Codecs that expose the T.261 block index (or Zarr chunking) can
    make this cheap; codecs that must fully decode to the end pay full cost.

    Note: this is a Python-side wall-clock measurement; con-duct captures the
    resource envelope of the enclosing invocation but not per-probe timing.
    """
    if window_samples > n_samples:
        raise ValueError("window_samples must be <= n_samples")
    if n_probes <= 0:
        return {"p50_s": 0.0, "p95_s": 0.0, "p99_s": 0.0, "mean_s": 0.0, "n_probes": 0}
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, n_samples - window_samples + 1, size=n_probes)
    times = np.empty(n_probes, dtype=np.float64)
    for i, start in enumerate(starts):
        t0 = time.perf_counter()
        chunk = fetch(int(start), int(window_samples))
        times[i] = time.perf_counter() - t0
        if chunk is None:
            raise RuntimeError("fetch returned None")
    return {
        "p50_s": float(np.percentile(times, 50)),
        "p95_s": float(np.percentile(times, 95)),
        "p99_s": float(np.percentile(times, 99)),
        "mean_s": float(np.mean(times)),
        "n_probes": int(n_probes),
    }


__all__ = [
    "compression_ratio",
    "prd",
    "prdn",
    "random_access_latency",
    "rmse",
    "round_trip_ok",
]
