"""Tests for the band-limited RMSE metric (Buccino et al. Fig 4-6 methodology)."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("scipy")

from compbench.metrics import rmse, rmse_band_limited


@pytest.mark.ai_generated
def test_band_limited_rmse_zero_for_identical() -> None:
    a = np.arange(30_000, dtype=np.float64).reshape(-1, 2)
    assert rmse_band_limited(a, a.copy(), 30_000.0) == 0.0


@pytest.mark.ai_generated
def test_band_limited_rejects_low_freq_error() -> None:
    """Error that is entirely below the pass-band should read as ~0 RMSE."""
    fs = 30_000.0
    n = 30_000
    t = np.arange(n) / fs
    orig = np.zeros((n, 1))
    # Reconstructed = orig + a slow 10 Hz drift → the ERROR is entirely
    # low-frequency; band-limited RMSE (300-6000 Hz) should reject it.
    recon = orig + 50.0 * np.sin(2 * np.pi * 10 * t)[:, None]
    full = rmse(orig, recon)
    band = rmse_band_limited(orig, recon, fs, 300, 6000)
    assert full > 30  # substantial full-band error
    # Away from filter transients, the residual should be small.
    assert band < 5  # band-limited error should be much smaller


@pytest.mark.ai_generated
def test_band_limited_preserves_in_band_error() -> None:
    """Error inside the pass-band should approximately equal full-band RMSE."""
    fs = 30_000.0
    n = 30_000
    t = np.arange(n) / fs
    orig = np.zeros((n, 1))
    # 1 kHz error signal — inside the 300-6000 Hz pass-band.
    recon = orig + 50.0 * np.sin(2 * np.pi * 1000 * t)[:, None]
    full = rmse(orig, recon)
    band = rmse_band_limited(orig, recon, fs, 300, 6000)
    # After filtfilt edge transients settle, they should be within ~10 %.
    assert 0.8 * full < band < 1.2 * full


@pytest.mark.ai_generated
def test_band_limited_rejects_bad_freqs() -> None:
    a = np.zeros((1000, 1))
    with pytest.raises(ValueError):
        rmse_band_limited(a, a, sample_rate_hz=500.0, low_hz=300, high_hz=6000)  # above Nyquist


@pytest.mark.ai_generated
def test_band_limited_1d_input_ok() -> None:
    fs = 30_000.0
    n = 30_000
    orig = np.zeros(n)
    recon = orig.copy()
    recon[10] = 100.0  # impulse
    band = rmse_band_limited(orig, recon, fs, 300, 6000)
    assert band > 0
