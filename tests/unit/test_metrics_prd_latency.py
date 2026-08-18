"""Unit tests for the PRD/PRDN and random-access-latency metrics."""

from __future__ import annotations

import time

import numpy as np
import pytest

from compbench.metrics import prd, prdn, random_access_latency


@pytest.mark.ai_generated
def test_prd_zero_for_identical() -> None:
    x = np.arange(100, dtype=np.float64)
    assert prd(x, x.copy()) == 0.0


@pytest.mark.ai_generated
def test_prd_known() -> None:
    # x = [1, 1, 1], x_hat = [1.1, 0.9, 1.1]
    # num = 0.01 + 0.01 + 0.01 = 0.03; denom = 3.0; sqrt(0.01) = 0.1 → 10 %
    x = np.array([1.0, 1.0, 1.0])
    xh = np.array([1.1, 0.9, 1.1])
    assert prd(x, xh) == pytest.approx(10.0, abs=0.001)


@pytest.mark.ai_generated
def test_prd_zero_input() -> None:
    x = np.zeros(10)
    xh = np.ones(10)
    assert prd(x, xh) == 0.0


@pytest.mark.ai_generated
def test_prd_shape_mismatch() -> None:
    with pytest.raises(ValueError):
        prd(np.zeros(5), np.zeros(6))


@pytest.mark.ai_generated
def test_prdn_zero_for_identical() -> None:
    x = np.arange(100, dtype=np.float64)
    assert prdn(x, x.copy()) == 0.0


@pytest.mark.ai_generated
def test_prdn_insensitive_to_dc_offset_in_denom() -> None:
    x = np.array([0.0, 1.0, 0.0, 1.0])  # mean = 0.5
    x_dc = x + 1000.0  # same variance, huge DC
    xh = x + 0.1  # small distortion
    xh_dc = x_dc + 0.1
    # PRDN normalises by variance around the mean → same for both series.
    assert prdn(x, xh) == pytest.approx(prdn(x_dc, xh_dc), abs=1e-9)


@pytest.mark.ai_generated
def test_prdn_constant_signal_returns_zero() -> None:
    x = np.full(10, 5.0)
    xh = np.full(10, 6.0)  # off by a constant; but denom is 0 (no variance)
    assert prdn(x, xh) == 0.0


@pytest.mark.ai_generated
def test_random_access_latency_basic() -> None:
    def fetch(start: int, length: int) -> np.ndarray:
        return np.zeros(length)

    result = random_access_latency(fetch, n_samples=100, window_samples=10, n_probes=5, seed=0)
    for k in ("p50_s", "p95_s", "p99_s", "mean_s"):
        assert result[k] >= 0.0
    assert result["n_probes"] == 5


@pytest.mark.ai_generated
def test_random_access_latency_orders_percentiles() -> None:
    """Slow fetches should produce ordered percentiles."""

    def slow_fetch(start: int, length: int) -> np.ndarray:
        time.sleep(0.001)
        return np.zeros(length)

    result = random_access_latency(slow_fetch, n_samples=100, window_samples=10, n_probes=8, seed=0)
    assert result["p50_s"] <= result["p95_s"] <= result["p99_s"]
    assert result["mean_s"] > 0


@pytest.mark.ai_generated
def test_random_access_latency_zero_probes() -> None:
    def fetch(start: int, length: int) -> np.ndarray:
        return np.zeros(length)

    result = random_access_latency(fetch, n_samples=100, window_samples=10, n_probes=0)
    assert result == {"p50_s": 0.0, "p95_s": 0.0, "p99_s": 0.0, "mean_s": 0.0, "n_probes": 0}


@pytest.mark.ai_generated
def test_random_access_latency_window_too_big() -> None:
    def fetch(start: int, length: int) -> np.ndarray:
        return np.zeros(length)

    with pytest.raises(ValueError, match="<="):
        random_access_latency(fetch, n_samples=10, window_samples=100)
