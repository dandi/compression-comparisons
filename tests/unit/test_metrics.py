"""Unit tests for compbench.metrics."""

from __future__ import annotations

import math

import numpy as np
import pytest

from compbench import metrics


@pytest.mark.ai_generated
def test_cr_basic() -> None:
    assert metrics.compression_ratio(100, 25) == pytest.approx(4.0)


@pytest.mark.ai_generated
def test_cr_zero_encoded_is_zero() -> None:
    assert metrics.compression_ratio(100, 0) == 0.0


@pytest.mark.ai_generated
def test_rmse_zero_for_identical() -> None:
    a = np.arange(50, dtype=np.int16)
    assert metrics.rmse(a, a.copy()) == 0.0


@pytest.mark.ai_generated
def test_rmse_known() -> None:
    a = np.array([1, 2, 3], dtype=np.int16)
    b = np.array([2, 3, 4], dtype=np.int16)
    # Diff = [-1,-1,-1] → RMSE = 1.0
    assert metrics.rmse(a, b) == pytest.approx(1.0)


@pytest.mark.ai_generated
def test_rmse_known_larger() -> None:
    a = np.array([0.0, 0.0, 0.0])
    b = np.array([1.0, -1.0, 2.0])
    # sqrt((1+1+4)/3)
    assert metrics.rmse(a, b) == pytest.approx(math.sqrt(6 / 3))


@pytest.mark.ai_generated
def test_rmse_shape_mismatch() -> None:
    with pytest.raises(ValueError):
        metrics.rmse(np.zeros(5), np.zeros(6))


@pytest.mark.ai_generated
def test_round_trip_ok_true() -> None:
    a = np.arange(10, dtype=np.int16)
    assert metrics.round_trip_ok(a, a.copy()) is True


@pytest.mark.ai_generated
def test_round_trip_ok_shape_diff() -> None:
    assert metrics.round_trip_ok(np.zeros(5), np.zeros(6)) is False


@pytest.mark.ai_generated
def test_round_trip_ok_dtype_diff() -> None:
    a = np.arange(5, dtype=np.int16)
    b = a.astype(np.int32)
    assert metrics.round_trip_ok(a, b) is False


@pytest.mark.ai_generated
def test_round_trip_ok_value_diff() -> None:
    a = np.zeros(5, dtype=np.int16)
    b = a.copy()
    b[0] = 1
    assert metrics.round_trip_ok(a, b) is False
