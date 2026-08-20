"""LSB correction — plan §4.6b(a), Buccino et al. 2023 §2.2.1.

Open Ephys rescales Neuropixels data to a fixed 0.195 uV/sample regardless
of hardware gain, which makes every raw sample an exact multiple of 12
(NP1) or 3 (NP2). Those log2(lsb) bits carry no information but codecs
still pay for them. The paper divides them out before compressing; the
headline figures all use LSB-corrected data.
"""

from __future__ import annotations

import numpy as np
import pytest

from compbench.preprocessing import apply, registered


def _open_ephys_like(lsb, n=2000, ch=8, seed=0):
    """Samples that are exact multiples of `lsb`, plus a per-channel DC offset."""
    rng = np.random.default_rng(seed)
    underlying = rng.normal(0, 50, size=(n, ch)).round().astype(np.int64)
    offsets = rng.integers(-300, 300, size=(1, ch))
    return (underlying * lsb + offsets).astype(np.int16), underlying


def _steps(**over):
    step = {"kind": "lsb_correction", "lsb": 12}
    step.update(over)
    return [step]


def test_registered():
    assert "lsb_correction" in registered()


@pytest.mark.parametrize("lsb", [12, 3])
def test_quantization_step_collapses_to_one(lsb):
    """The whole point: after correction, adjacent codes differ by 1, not by lsb."""
    data, _ = _open_ephys_like(lsb)
    before = np.diff(np.unique(data[:, 0])).min()
    after = np.diff(np.unique(apply(data, 30000.0, _steps(lsb=lsb))[:, 0])).min()
    assert before == lsb
    assert after == 1


@pytest.mark.parametrize("lsb", [12, 3])
def test_recovers_the_underlying_median_centred_signal(lsb):
    data, underlying = _open_ephys_like(lsb)
    got = apply(data, 30000.0, _steps(lsb=lsb))
    for c in range(data.shape[1]):
        expected = (underlying[:, c] - np.median(underlying[:, c])).astype(np.int16)
        np.testing.assert_array_equal(got[:, c], expected)


def test_lsb_one_is_a_no_op():
    """SpikeGLX case.

    `spikeinterface.preprocessing.correct_lsb` warns "Estimated LSB=1. No
    operation is applied" and returns the recording untouched, and the
    paper's driver marks IBL as `{"none": False}` — the untouched
    recording goes to the compressor. Removing the median anyway is a step
    the paper never applied; on CSHZAD026 it inflates blosc-zstd CR by
    >20%, which is enough to look like a failed reproduction.
    """
    rng = np.random.default_rng(1)
    data = (rng.normal(0, 50, size=(2000, 4)) + 800).round().astype(np.int16)
    got = apply(data, 30000.0, _steps(lsb=1))
    np.testing.assert_array_equal(got, data)
    assert abs(float(np.median(got[:, 0]))) > 700  # offset deliberately preserved


def test_it_actually_improves_compression():
    """The claim behind the whole step, measured rather than asserted."""
    import zlib

    data, _ = _open_ephys_like(12, n=8000, ch=16)
    corrected = apply(data, 30000.0, _steps(lsb=12))
    raw_size = len(zlib.compress(data.tobytes(), 5))
    corrected_size = len(zlib.compress(corrected.tobytes(), 5))
    assert corrected_size < raw_size


def test_dtype_shape_and_contiguity_preserved():
    data, _ = _open_ephys_like(12)
    got = apply(data, 30000.0, _steps())
    assert got.dtype == data.dtype
    assert got.shape == data.shape
    assert got.flags["C_CONTIGUOUS"]


def test_one_dimensional_input():
    rng = np.random.default_rng(2)
    data = (rng.normal(0, 50, size=4000).round().astype(np.int64) * 12).astype(np.int16)
    got = apply(data, 30000.0, _steps())
    assert got.shape == data.shape
    assert np.diff(np.unique(got)).min() == 1


@pytest.mark.parametrize("block_bytes", [2 * 1024**3, 16000, 8])
def test_block_size_does_not_change_output(block_bytes):
    """Per-channel median needs the whole time axis; blocking is by channel."""
    data, _ = _open_ephys_like(12, ch=9)
    reference = apply(data, 30000.0, _steps())
    np.testing.assert_array_equal(
        apply(data, 30000.0, _steps(max_block_bytes=block_bytes)), reference
    )


def test_rejects_nonpositive_lsb():
    data, _ = _open_ephys_like(12)
    with pytest.raises(ValueError, match="positive integer"):
        apply(data, 30000.0, _steps(lsb=0))


def test_composes_after_bandpass_in_a_chain():
    """Order matters and must be whatever the YAML says; both must run."""
    data, _ = _open_ephys_like(12, n=6000)
    chain = [
        {"kind": "lsb_correction", "lsb": 12},
        {"kind": "bandpass", "low_hz": 300, "high_hz": 6000, "order": 4},
    ]
    got = apply(data, 30000.0, chain)
    assert got.shape == data.shape
    assert got.dtype == data.dtype
