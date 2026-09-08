"""H5 band splitting: the split must be exact, or every fidelity number lies.

`split_bands` is the load-bearing part. If `lo + hi != x` the codec has a
reconstruction floor that no QP can get under, and every band-split fidelity
result would be measuring the splitter rather than the codec. These tests do
not need the BWC binaries — they exercise the split itself.
"""

from __future__ import annotations

import numpy as np
import pytest

from compbench.codecs.t261_bandsplit import split_bands


def _recording(n=8192, ch=6, seed=0):
    """Broadband noise plus a slow drift plus spikes — LFP and spike content."""
    rng = np.random.default_rng(seed)
    t = np.arange(n)[:, None]
    lfp = 120.0 * np.sin(2 * np.pi * 5.0 * t / 30000.0)
    noise = rng.normal(0, 12.0, size=(n, ch))
    x = lfp + noise
    for c in range(ch):  # a few 1 ms negative spikes
        for s in rng.choice(n - 40, size=5, replace=False):
            x[s : s + 30, c] -= 200.0 * np.hanning(30)
    return np.ascontiguousarray(np.rint(x).astype(np.int16))


def test_split_is_exact():
    """lo + hi == x bit-for-bit. This is the whole design premise."""
    x = _recording()
    lo, hi = split_bands(x, 30000.0, 300.0)
    assert np.array_equal(lo.astype(np.int32) + hi.astype(np.int32), x.astype(np.int32))


def test_split_is_exact_across_cutoffs_and_orders():
    x = _recording(seed=3)
    for split_hz in (100.0, 300.0, 1300.0, 6000.0):
        for order in (2, 4, 6):
            lo, hi = split_bands(x, 30000.0, split_hz, order)
            assert np.array_equal(
                lo.astype(np.int32) + hi.astype(np.int32), x.astype(np.int32)
            ), f"split not exact at {split_hz} Hz order {order}"


def test_bands_are_int16():
    x = _recording()
    lo, hi = split_bands(x, 30000.0, 300.0)
    assert lo.dtype == np.int16 and hi.dtype == np.int16


def test_low_band_actually_holds_the_low_frequencies():
    """A splitter that returned (x, 0) would pass the exactness test."""
    x = _recording()
    lo, hi = split_bands(x, 30000.0, 300.0)
    # The 5 Hz drift dominates the low band and must be largely absent above it.
    assert lo.std() > 50, "low band lost the 5 Hz drift"
    assert hi.std() < lo.std(), "high band should carry less power than the LFP here"
    # And the high band must retain the spikes: its extremes stay large.
    assert np.abs(hi).max() > 50, "high band lost the spikes"


def test_1d_input_is_accepted():
    x = _recording(ch=1)[:, 0]
    lo, hi = split_bands(x, 30000.0, 300.0)
    assert lo.shape == (x.size, 1)
    assert np.array_equal(
        (lo.astype(np.int32) + hi.astype(np.int32)).ravel(), x.astype(np.int32)
    )


@pytest.mark.parametrize("bad", [0.0, -1.0, 15000.0, 20000.0])
def test_cutoff_outside_nyquist_is_rejected(bad):
    """A cutoff at or above Nyquist is a silent no-op in some filter designs."""
    with pytest.raises(ValueError, match="split_hz"):
        split_bands(_recording(n=1024), 30000.0, bad)


def test_sample_rate_changes_the_split():
    """fs is required precisely because it changes the answer — MEArec is
    32 kHz while IBL/AIND are 30 kHz, and a wrong default would be invisible.
    """
    x = _recording()
    lo30, _ = split_bands(x, 30000.0, 300.0)
    lo32, _ = split_bands(x, 32000.0, 300.0)
    assert not np.array_equal(lo30, lo32)


def test_adapter_lossy_flag_matches_the_plain_t261_rule_per_band():
    """Same rule as `T261Adapter`, applied to each band.

    The split itself is exact, so losslessness is decided by the preset and
    the two QPs alone. Note a non-`_lossless` preset is lossy at ANY QP even
    though QP 1.0 happens to round-trip bit-exactly in practice — that is
    `T261Adapter`'s existing semantics and this must not diverge from it.
    """
    from compbench.codecs import get, names

    if "t261-bandsplit" not in names():
        pytest.skip("BWC binaries unavailable")
    cls = get("t261-bandsplit")
    lossless = "combinedPresetEEG_IndepChannel_lossless"
    assert cls(sample_rate_hz=30000, preset=lossless).lossy is False
    assert cls(sample_rate_hz=30000, preset=lossless, qp_hi=5.0).lossy is True
    assert cls(sample_rate_hz=30000, preset="r0-stock", qp_lo=1.0, qp_hi=1.0).lossy is True
    assert cls(sample_rate_hz=30000, preset="r0-stock", qp_lo=1.0, qp_hi=5.0).lossy is True


def test_adapter_constructs_without_args_but_refuses_to_encode():
    """`codecs.all_adapters()` constructs every adapter generically, so
    `cls()` must work — but a defaulted sample rate would silently place the
    crossover ~7 % wrong on one substrate, so `make_codec()` refuses instead.
    """
    from compbench.codecs import get, names

    if "t261-bandsplit" not in names():
        pytest.skip("BWC binaries unavailable")
    cls = get("t261-bandsplit")
    adapter = cls()  # must not raise
    with pytest.raises(ValueError, match="requires sample_rate_hz"):
        adapter.make_codec()
    cls(sample_rate_hz=30000).make_codec()  # and works once given one
