"""`distortion_summary` — chunked distortion metrics (plan §Phase 3.5 [R5-H2], [R1-H2]).

The whole point of the blocked implementation is that it is *numerically
identical* to the naive whole-array path while using bounded memory. These
tests pin that equivalence, including at block sizes small enough to force
many blocks, so a future "optimisation" can't silently change the numbers
in published tables.
"""

from __future__ import annotations

import numpy as np
import pytest

from compbench import metrics


def _signal(n_samples=4096, n_channels=8, seed=0, fs=30000.0):
    rng = np.random.default_rng(seed)
    # Per-channel DC offsets + differing gains: exercises the parallel-axis
    # recombination and the per-channel normalisers.
    base = rng.normal(0, 200, size=(n_samples, n_channels))
    base += rng.integers(-500, 500, size=(1, n_channels))
    base *= rng.uniform(0.5, 2.0, size=(1, n_channels))
    orig = base.astype(np.int16)
    noise = rng.integers(-3, 4, size=orig.shape).astype(np.int16)
    return orig, (orig + noise).astype(np.int16), fs


@pytest.mark.parametrize("max_block_bytes", [2 * 1024**3, 4096, 512])
def test_matches_naive_implementations(max_block_bytes):
    orig, recon, fs = _signal()
    got = metrics.distortion_summary(orig, recon, fs, max_block_bytes=max_block_bytes)

    assert got["rmse"] == pytest.approx(metrics.rmse(orig, recon), rel=1e-12)
    assert got["prd_percent"] == pytest.approx(metrics.prd(orig, recon), rel=1e-10)
    assert got["prdn_percent"] == pytest.approx(metrics.prdn(orig, recon), rel=1e-10)
    assert got["signal_std"] == pytest.approx(float(np.std(orig.astype(np.float64))), rel=1e-10)
    assert got["rmse_band_limited"] == pytest.approx(
        metrics.rmse_band_limited(orig, recon, fs), rel=1e-10
    )


def test_block_size_does_not_change_results():
    """Blocking is an implementation detail; results must not depend on it."""
    orig, recon, fs = _signal(n_samples=8192, n_channels=16)
    big = metrics.distortion_summary(orig, recon, fs, max_block_bytes=2 * 1024**3)
    small = metrics.distortion_summary(orig, recon, fs, max_block_bytes=1024)
    for key, value in big.items():
        if value is None:
            assert small[key] is None
        else:
            assert small[key] == pytest.approx(value, rel=1e-10), key


def test_per_channel_prdn_beats_pooled_on_heterogeneous_channels():
    """[R1-H2]: pooling std across channels understates per-channel distortion.

    Build channels with very different amplitudes but the same absolute
    error. The pooled normaliser is dominated by the loud channels, so the
    pooled PRDN reads far lower than the typical channel's.
    """
    rng = np.random.default_rng(1)
    n = 4096
    quiet = rng.normal(0, 10, size=(n, 8))
    loud = rng.normal(0, 1000, size=(n, 8))
    orig = np.hstack([quiet, loud]).astype(np.int16)
    recon = (orig + rng.integers(-3, 4, size=orig.shape)).astype(np.int16)

    got = metrics.distortion_summary(orig, recon, 30000.0)
    assert got["prdn_per_channel_median_percent"] > got["prdn_percent"]
    assert got["prdn_per_channel_max_percent"] >= got["prdn_per_channel_median_percent"]
    assert got["prdn_per_channel_iqr_percent"] > 0


def test_lossless_input_is_all_zero_distortion():
    orig, _, fs = _signal()
    got = metrics.distortion_summary(orig, orig.copy(), fs)
    assert got["rmse"] == 0.0
    assert got["prd_percent"] == 0.0
    assert got["prdn_percent"] == 0.0
    assert got["rmse_band_limited"] == 0.0
    assert got["prdn_per_channel_median_percent"] == 0.0
    assert got["signal_std"] > 0


def test_band_limited_is_none_below_nyquist_gate():
    orig, recon, _ = _signal(fs=1000.0)
    got = metrics.distortion_summary(orig, recon, 1000.0)
    assert got["rmse_band_limited"] is None
    assert got["rmse"] > 0  # the rest of the metrics still compute


def test_one_dimensional_input_treated_as_single_channel():
    rng = np.random.default_rng(2)
    orig = rng.integers(-1000, 1000, size=8192).astype(np.int16)
    recon = (orig + rng.integers(-2, 3, size=orig.shape)).astype(np.int16)
    got = metrics.distortion_summary(orig, recon, 30000.0)
    assert got["rmse"] == pytest.approx(metrics.rmse(orig, recon), rel=1e-12)
    # A single channel's PRDN is the pooled PRDN.
    assert got["prdn_per_channel_median_percent"] == pytest.approx(got["prdn_percent"], rel=1e-10)


def test_flat_channels_are_excluded_not_infinite():
    """A dead channel has no variance to normalise by; it must not poison the stats."""
    rng = np.random.default_rng(3)
    live = rng.normal(0, 300, size=(4096, 4))
    dead = np.zeros((4096, 2))
    orig = np.hstack([live, dead]).astype(np.int16)
    recon = orig.copy()
    recon[:, 0] += 5
    got = metrics.distortion_summary(orig, recon, 30000.0)
    assert np.isfinite(got["prdn_per_channel_median_percent"])
    assert np.isfinite(got["prdn_per_channel_max_percent"])


def test_empty_input_returns_zeros():
    empty = np.zeros((0, 4), dtype=np.int16)
    got = metrics.distortion_summary(empty, empty, 30000.0)
    assert got["rmse"] == 0.0
    assert got["rmse_band_limited"] is None
