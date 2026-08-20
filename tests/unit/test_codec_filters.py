"""Zarr-style pre-compression filters — the shuffle and delta axes.

Buccino et al. apply these as Zarr `filters`, ahead of the compressor.
Both are axes we previously could not express at all, and both move CR
by more than our reproduction tolerance, so they are not optional.
"""

from __future__ import annotations

import numpy as np
import pytest

from compbench.codecs import get as get_codec
from compbench.codecs.filters import DELTA_VARIANTS, Delta2D, make_delta_filter
from compbench.datasets.base import LoadedDataset
from compbench.runner import decode, encode

NON_BLOSC = ["gzip", "zlib", "lz4", "zstd", "lzma"]


def _signal(n=2000, ch=16, seed=0):
    rng = np.random.default_rng(seed)
    return np.cumsum(rng.normal(0, 40, size=(n, ch)), axis=0).astype(np.int16)


# ---- Delta2D ------------------------------------------------------------


@pytest.mark.parametrize("axis", [0, 1, "both"])
def test_delta2d_round_trip_is_exact(axis):
    data = _signal()
    f = Delta2D(axis=axis)
    np.testing.assert_array_equal(f.decode(f.encode(data)), data)


def test_delta2d_wraps_losslessly_at_int16_extremes():
    """Differencing int16 overflows by design; the inverse cumsum must wrap back."""
    data = np.array([[-32768, 32767, -32768], [32767, -32768, 32767]], dtype=np.int16).T.copy()
    f = Delta2D(axis=0)
    np.testing.assert_array_equal(f.decode(f.encode(data)), data)


def test_delta2d_time_axis_shrinks_a_random_walk():
    """The reason the filter exists: it decorrelates along time."""
    data = _signal()
    encoded = Delta2D(axis=0).encode(data)
    assert encoded.std() < data.std() / 5


def test_delta2d_rejects_1d_input():
    with pytest.raises(ValueError, match="2-D chunk"):
        Delta2D(axis=0).encode(np.zeros(10, dtype=np.int16))


def test_delta2d_rejects_bad_axis():
    with pytest.raises(ValueError, match="axis must be"):
        Delta2D(axis=2)


# ---- variant mapping ----------------------------------------------------


def test_1d_is_numcodecs_delta_not_a_time_delta():
    """The trap: mapping `1d` onto Delta2D(axis=0) would turn the paper's
    known-WORST delta condition into its best."""
    from numcodecs import Delta

    assert isinstance(make_delta_filter("1d"), Delta)
    assert isinstance(make_delta_filter("2d-time"), Delta2D)


def test_no_variant_means_no_filter_at_all():
    assert make_delta_filter("no") is None


def test_all_paper_variants_are_constructible():
    assert set(DELTA_VARIANTS) == {"no", "1d", "2d-time", "2d-space", "2d-time-space"}
    for v in DELTA_VARIANTS:
        make_delta_filter(v)


def test_unknown_variant_rejected():
    with pytest.raises(ValueError, match="delta must be one of"):
        make_delta_filter("2d-frequency")


# ---- adapter integration ------------------------------------------------


@pytest.mark.parametrize("name", NON_BLOSC)
def test_byte_shuffle_is_exposed_on_every_non_blosc_codec(name):
    """Paper table 2 gives all five a `(no, byte)` axis; we could express none."""
    plain = get_codec(name)()
    shuffled = get_codec(name)(shuffle="byte")
    assert plain.make_filters() == []
    cfg = shuffled.describe()["filters"]
    assert cfg == [{"id": "shuffle", "elementsize": 2}]


@pytest.mark.parametrize("name", NON_BLOSC)
def test_shuffled_round_trip_is_exact(name):
    ds = LoadedDataset(data=_signal(), sample_rate_hz=30000.0)
    ad = get_codec(name)(shuffle="byte")
    bufs, _ = encode(ds, ad)
    out, _ = decode(bufs, ad, template=ds.data)
    np.testing.assert_array_equal(out, ds.data)


def test_shuffle_rejects_blosc_only_bit_option():
    """`bit` is blosc's internal shuffle, a different mechanism."""
    with pytest.raises(ValueError, match="shuffle must be one of"):
        get_codec("lzma")(shuffle="bit")


@pytest.mark.parametrize("variant", ["1d", "2d-time", "2d-space", "2d-time-space"])
def test_delta_round_trip_through_the_full_adapter_chain(variant):
    ds = LoadedDataset(data=_signal(), sample_rate_hz=30000.0)
    ad = get_codec("blosc-zstd")(level=9, shuffle="bit", delta=variant)
    bufs, _ = encode(ds, ad, chunk_samples=500)
    out, _ = decode(bufs, ad, template=ds.data, chunk_samples=500)
    np.testing.assert_array_equal(out, ds.data)


def test_delta_and_shuffle_compose_in_order():
    """Delta first, then shuffle — Zarr applies a filter list in order."""
    ad = get_codec("lzma")(preset=9, shuffle="byte", delta="2d-time")
    ids = [f["id"] for f in ad.describe()["filters"]]
    assert ids == ["compbench.delta2d", "shuffle"]


def test_delta_and_shuffle_together_round_trip():
    ds = LoadedDataset(data=_signal(), sample_rate_hz=30000.0)
    ad = get_codec("lzma")(preset=9, shuffle="byte", delta="2d-time")
    bufs, _ = encode(ds, ad, chunk_samples=500)
    out, _ = decode(bufs, ad, template=ds.data, chunk_samples=500)
    np.testing.assert_array_equal(out, ds.data)


def test_filters_are_recorded_in_the_codec_description():
    """A filter changes the bytes without changing the codec name — exactly
    the kind of condition that silently makes two cells incomparable."""
    assert "filters" not in get_codec("lzma")(preset=9).describe()
    desc = get_codec("lzma")(preset=9, delta="2d-time").describe()
    assert desc["filters"][0]["id"] == "compbench.delta2d"
    assert desc["params"]["delta"] == "2d-time"


def test_delta_actually_improves_compression_on_correlated_data():
    """Measured, not asserted — this is the paper's Fig 7(a) claim."""
    ds = LoadedDataset(data=_signal(), sample_rate_hz=30000.0)
    plain = get_codec("blosc-zstd")(level=9, shuffle="bit")
    delta = get_codec("blosc-zstd")(level=9, shuffle="bit", delta="2d-time")
    n_plain = sum(map(len, encode(ds, plain)[0]))
    n_delta = sum(map(len, encode(ds, delta)[0]))
    assert n_delta < n_plain


def test_unknown_delta_rejected_at_adapter_construction():
    with pytest.raises(ValueError, match="delta must be one of"):
        get_codec("blosc-zstd")(level=9, delta="nope")
