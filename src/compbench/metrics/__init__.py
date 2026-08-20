"""Correctness metrics: CR, RMSE, round-trip byte-equality, PRD/PRDN, latency."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import numpy as np


def compression_ratio(original_bytes: int, encoded_bytes: int) -> float:
    """`original / encoded`. Undefined for empty input; returns 0.0."""
    if encoded_bytes <= 0:
        return 0.0
    return original_bytes / encoded_bytes


def rmse(original: np.ndarray, reconstructed: np.ndarray) -> float:
    """Root-mean-square error in the units of the input.

    Note: this is the *full-band* RMSE. For spike-band ephys distortion
    (Buccino et al. Fig 4-6 methodology), use `rmse_band_limited()` which
    filters the reconstruction error before computing.
    """
    if original.shape != reconstructed.shape:
        raise ValueError(
            f"Shape mismatch: original {original.shape} vs reconstructed {reconstructed.shape}"
        )
    if original.dtype != reconstructed.dtype:
        # Coerce reconstructed to original dtype before diff to catch codec dtype bugs.
        reconstructed = reconstructed.astype(original.dtype)
    diff = original.astype(np.float64) - reconstructed.astype(np.float64)
    return float(np.sqrt(np.mean(diff * diff)))


def rmse_band_limited(
    original: np.ndarray,
    reconstructed: np.ndarray,
    sample_rate_hz: float,
    low_hz: float = 300.0,
    high_hz: float = 6000.0,
    order: int = 4,
) -> float:
    """RMSE of the band-limited reconstruction error.

    Buccino et al. 2023 methodology: compute (original - reconstructed),
    filter the error signal through a 300-6000 Hz band-pass, then RMSE.
    This isolates the codec's distortion in the spike band, independent of
    whether the codec was applied to raw or already-filtered data.

    Requires scipy. Filters per-channel (axis=0) via zero-phase
    Butterworth. On the paper's Fig 4-6 y-axis this is the "RMSE".
    """
    from scipy.signal import butter, filtfilt

    if original.shape != reconstructed.shape:
        raise ValueError(
            f"Shape mismatch: original {original.shape} vs reconstructed {reconstructed.shape}"
        )
    nyq = 0.5 * float(sample_rate_hz)
    if not 0 < low_hz < high_hz < nyq:
        raise ValueError(
            f"bandpass requires 0 < low ({low_hz}) < high ({high_hz}) < Nyquist ({nyq})"
        )
    b, a = butter(int(order), [low_hz / nyq, high_hz / nyq], btype="band")
    err = original.astype(np.float64) - reconstructed.astype(np.float64)
    if err.ndim == 1:
        err = err[:, None]
    filtered = filtfilt(b, a, err, axis=0)
    return float(np.sqrt(np.mean(filtered * filtered)))


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


_DEFAULT_BLOCK_BYTES = 2 * 1024**3  # 2 GiB per float64 working array


def _as_2d(a: np.ndarray) -> np.ndarray:
    return a[:, None] if a.ndim == 1 else a


def signal_std(arr: np.ndarray, max_block_bytes: int = _DEFAULT_BLOCK_BYTES) -> float:
    """Population standard deviation without promoting the whole array.

    `np.std(a.astype(np.float64))` costs 4x the input in peak RSS — 110 GB
    on a 27 GB int16 recording, paid even by lossless cells that need no
    other distortion metric at all.
    """
    a = _as_2d(arr)
    n_samples, n_channels = a.shape
    total_n = float(n_samples) * n_channels
    if total_n == 0:
        return 0.0
    row_bytes = n_channels * 8
    rows_per_block = max(1, min(n_samples, max_block_bytes // max(row_bytes, 1)))
    acc_sum = 0.0
    acc_sumsq = 0.0
    for start in range(0, n_samples, rows_per_block):
        block = a[start : start + rows_per_block].astype(np.float64)
        acc_sum += float(block.sum())
        acc_sumsq += float(np.einsum("ij,ij->", block, block))
        del block
    mean = acc_sum / total_n
    var = max(acc_sumsq / total_n - mean * mean, 0.0)
    return float(np.sqrt(var))


def distortion_summary(
    original: np.ndarray,
    reconstructed: np.ndarray,
    sample_rate_hz: float,
    low_hz: float = 300.0,
    high_hz: float = 6000.0,
    order: int = 4,
    max_block_bytes: int = _DEFAULT_BLOCK_BYTES,
) -> dict[str, Any]:
    """Every distortion metric for one cell, in bounded memory.

    The naive path — promote both arrays to float64 and hand them to five
    independent metric functions — costs ~8x the input size in peak RSS. On
    the paper's full 1200 s recordings (27 GB int16) that is ~500 GB per
    cell, which caps a 1 TB box at two concurrent lossy cells and OOMs
    anything smaller (plan §Phase 3.5 [R5-H2]).

    Here every statistic is accumulated over blocks, so peak working set is
    a few GB regardless of recording length:

    * **Time-blocked pass** (contiguous, cache-friendly) accumulates
      per-channel `n`, `sum(x)`, `sum(x^2)`, `sum((x-x_hat)^2)`. RMSE, PRD,
      PRDN, signal std and the per-channel PRDN distribution all fall out
      of those four sums exactly — no second pass, no full-array float64.
    * **Channel-blocked pass** handles the band-limited RMSE, which needs
      the whole time axis per channel to filter. `filtfilt` along axis=0 is
      independent per channel, so blocking by channel is exact — unlike
      blocking by time, which would inject edge transients at every seam.

    Returns a dict with the same keys `run_cell` writes into `metrics.json`,
    plus the per-channel PRDN summary ([R1-H2]): pooling the standard
    deviation across all 384 channels understates typical per-channel
    distortion, so the reader-facing number should be the per-channel
    median, not the pooled one.
    """
    if original.shape != reconstructed.shape:
        raise ValueError(
            f"Shape mismatch: original {original.shape} vs reconstructed {reconstructed.shape}"
        )
    x2d = _as_2d(original)
    r2d = _as_2d(reconstructed)
    n_samples, n_channels = x2d.shape
    if n_samples == 0 or n_channels == 0:
        return {
            "rmse": 0.0,
            "prd_percent": 0.0,
            "prdn_percent": 0.0,
            "signal_std": 0.0,
            "rmse_band_limited": None,
            "prdn_per_channel_median_percent": None,
            "prdn_per_channel_iqr_percent": None,
            "prdn_per_channel_max_percent": None,
        }

    # ---- Pass A: time blocks, contiguous reads -----------------------------
    per_ch_sum = np.zeros(n_channels, dtype=np.float64)
    per_ch_sumsq = np.zeros(n_channels, dtype=np.float64)
    per_ch_err2 = np.zeros(n_channels, dtype=np.float64)

    row_bytes = n_channels * 8
    rows_per_block = max(1, min(n_samples, max_block_bytes // max(row_bytes, 1)))
    for start in range(0, n_samples, rows_per_block):
        stop = min(start + rows_per_block, n_samples)
        xb = x2d[start:stop].astype(np.float64)
        rb = r2d[start:stop].astype(np.float64)
        per_ch_sum += xb.sum(axis=0)
        per_ch_sumsq += np.einsum("ij,ij->j", xb, xb)
        rb -= xb  # reuse rb as the error block; avoids a third allocation
        per_ch_err2 += np.einsum("ij,ij->j", rb, rb)
        del xb, rb

    n_per_ch = float(n_samples)
    total_n = float(n_samples) * n_channels
    per_ch_mean = per_ch_sum / n_per_ch
    # sum((x - mean)^2) per channel. For ephys the per-channel mean is small
    # next to the std, so this subtraction is numerically comfortable in
    # float64 (it loses ~log10(mean^2/var) digits out of ~16).
    per_ch_centred = np.maximum(per_ch_sumsq - n_per_ch * per_ch_mean**2, 0.0)

    total_err2 = float(per_ch_err2.sum())
    total_sumsq = float(per_ch_sumsq.sum())
    grand_mean = float(per_ch_sum.sum() / total_n)
    # Parallel-axis theorem: recentre each channel's SS on the grand mean so
    # the pooled figure matches np.std(whole_array) exactly.
    total_centred = float((per_ch_centred + n_per_ch * (per_ch_mean - grand_mean) ** 2).sum())

    rmse_val = float(np.sqrt(total_err2 / total_n))
    prd_val = 100.0 * float(np.sqrt(total_err2 / total_sumsq)) if total_sumsq > 0 else 0.0
    prdn_val = 100.0 * float(np.sqrt(total_err2 / total_centred)) if total_centred > 0 else 0.0
    signal_std = float(np.sqrt(total_centred / total_n))

    # Per-channel PRDN — channels with a flat trace (zero variance) have no
    # meaningful normaliser and are dropped rather than reported as inf.
    prdn_median: float | None
    prdn_iqr: float | None
    prdn_max: float | None
    live = per_ch_centred > 0
    if live.any():
        prdn_ch = 100.0 * np.sqrt(per_ch_err2[live] / per_ch_centred[live])
        q75, q25 = np.percentile(prdn_ch, [75, 25])
        prdn_median = float(np.median(prdn_ch))
        prdn_iqr = float(q75 - q25)
        prdn_max = float(prdn_ch.max())
    else:
        prdn_median = prdn_iqr = prdn_max = None

    # ---- Pass B: channel blocks, for the band-limited error ---------------
    band_rmse = _band_limited_rmse_blocked(
        x2d, r2d, sample_rate_hz, low_hz, high_hz, order, max_block_bytes
    )

    return {
        "rmse": rmse_val,
        "prd_percent": prd_val,
        "prdn_percent": prdn_val,
        "signal_std": signal_std,
        "rmse_band_limited": band_rmse,
        "prdn_per_channel_median_percent": prdn_median,
        "prdn_per_channel_iqr_percent": prdn_iqr,
        "prdn_per_channel_max_percent": prdn_max,
    }


def _band_limited_rmse_blocked(
    x2d: np.ndarray,
    r2d: np.ndarray,
    sample_rate_hz: float,
    low_hz: float,
    high_hz: float,
    order: int,
    max_block_bytes: int,
) -> float | None:
    """Band-limited RMSE accumulated over channel blocks; None if out of band.

    Nyquist gate matches `run_cell`'s: a 300-6000 Hz band needs the sample
    rate above 12 kHz, which excludes the synthetic low-rate fixtures.
    """
    nyq = 0.5 * float(sample_rate_hz)
    if not 0 < low_hz < high_hz < nyq:
        return None
    from scipy.signal import butter, filtfilt

    b, a = butter(int(order), [low_hz / nyq, high_hz / nyq], btype="band")
    n_samples, n_channels = x2d.shape
    col_bytes = n_samples * 8
    cols_per_block = max(1, min(n_channels, max_block_bytes // max(col_bytes, 1)))

    total = 0.0
    for c0 in range(0, n_channels, cols_per_block):
        c1 = min(c0 + cols_per_block, n_channels)
        err = x2d[:, c0:c1].astype(np.float64)
        err -= r2d[:, c0:c1].astype(np.float64)
        filtered = filtfilt(b, a, err, axis=0)
        total += float(np.einsum("ij,ij->", filtered, filtered))
        del err, filtered
    return float(np.sqrt(total / (float(n_samples) * n_channels)))


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
    "distortion_summary",
    "prd",
    "prdn",
    "random_access_latency",
    "rmse",
    "rmse_band_limited",
    "round_trip_ok",
    "signal_std",
]
