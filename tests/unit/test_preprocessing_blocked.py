"""Channel-blocked band-pass must be bit-identical to the whole-array form.

Plan §Phase 3.5 [R5-C1]: the whole-array path promotes a 27 GB int16
recording to 110 GB of float64 and hands that to `filtfilt`, peaking near
200-250 GB. Blocking by channel fixes that — and because the filter runs
along the time axis independently per channel, it must not change a single
output sample. These tests are what stop a memory optimisation from
quietly moving published band-pass compression ratios.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy.signal import butter, filtfilt

from compbench.preprocessing import apply


def _reference_whole_array(data, fs, low=300.0, high=6000.0, order=4):
    """The pre-blocking implementation, kept here as the oracle."""
    nyq = 0.5 * fs
    b, a = butter(order, [low / nyq, high / nyq], btype="band")
    filtered = filtfilt(b, a, data.astype(np.float64), axis=0)
    np.round(filtered, out=filtered)
    return np.ascontiguousarray(filtered.astype(data.dtype))


def _steps(**over):
    step = {"kind": "bandpass", "low_hz": 300, "high_hz": 6000, "order": 4}
    step.update(over)
    return [step]


@pytest.mark.parametrize("n_channels", [1, 2, 7, 32])
def test_blocked_matches_whole_array_bit_for_bit(n_channels):
    rng = np.random.default_rng(0)
    fs = 30000.0
    data = rng.normal(0, 300, size=(6000, n_channels)).astype(np.int16)
    got = apply(data, fs, _steps())
    np.testing.assert_array_equal(got, _reference_whole_array(data, fs))


@pytest.mark.parametrize("block_bytes", [2 * 1024**3, 1024**2, 48000, 8])
def test_block_size_does_not_change_output(block_bytes):
    """Forcing one channel per block must give the same samples as one big block."""
    rng = np.random.default_rng(1)
    fs = 30000.0
    data = rng.normal(0, 300, size=(6000, 16)).astype(np.int16)
    got = apply(data, fs, _steps(max_block_bytes=block_bytes))
    np.testing.assert_array_equal(got, _reference_whole_array(data, fs))


def test_output_dtype_shape_and_contiguity_preserved():
    rng = np.random.default_rng(2)
    data = rng.normal(0, 300, size=(4096, 9)).astype(np.int16)
    got = apply(data, 30000.0, _steps())
    assert got.dtype == np.int16
    assert got.shape == data.shape
    assert got.flags["C_CONTIGUOUS"]


def test_one_dimensional_input_round_trips_shape():
    rng = np.random.default_rng(3)
    data = rng.normal(0, 300, size=6000).astype(np.int16)
    got = apply(data, 30000.0, _steps())
    assert got.shape == data.shape
    np.testing.assert_array_equal(got, _reference_whole_array(data[:, None], 30000.0).ravel())


def test_clipping_is_detected_across_blocks():
    """The clip check accumulates a peak over blocks; a late channel must still trip it."""
    rng = np.random.default_rng(4)
    data = rng.normal(0, 100, size=(6000, 8)).astype(np.int16)
    # Put a full-scale square wave in the LAST channel only — with a naive
    # per-block check that forgot to accumulate, this would slip through.
    data[:, -1] = np.where(np.arange(6000) % 4 < 2, 32767, -32768)
    with pytest.raises(ValueError, match="would clip"):
        apply(data, 30000.0, _steps(max_block_bytes=8))


def test_float_input_is_not_rounded_or_clip_checked():
    rng = np.random.default_rng(5)
    data = rng.normal(0, 3.0, size=(4096, 4)).astype(np.float32)
    got = apply(data, 30000.0, _steps())
    assert got.dtype == np.float32
    assert not np.all(got == np.round(got))
