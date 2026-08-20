"""Chunked compression — plan §4.6b(b).

Buccino et al. compress through a Zarr store whose chunks are
(chunk_samples, n_channels), and every headline figure filters to a 1 s
chunk. Compressing a whole 60 s buffer in one shot gives the codec far
more context and a better ratio, so the two conditions are not
comparable. These tests pin the chunking semantics and — importantly —
that the default stays whole-buffer so existing derivatives keep their
cell IDs.
"""

from __future__ import annotations

from itertools import pairwise

import numpy as np
import pytest

from compbench.codecs import get as get_codec
from compbench.datasets.base import LoadedDataset
from compbench.pipeline.profile import expand_matrix, load_profile
from compbench.runner import chunk_bounds, decode, encode, run_cell


def _ds(n=3000, ch=4, fs=1000.0, seed=0):
    rng = np.random.default_rng(seed)
    data = rng.integers(-2000, 2000, size=(n, ch)).astype(np.int16)
    return LoadedDataset(data=data, sample_rate_hz=fs)


def _adapter(name="blosc-zstd", **params):
    return get_codec(name)(**params)


# ---- chunk_bounds ------------------------------------------------------


def test_none_is_a_single_whole_buffer_chunk():
    assert chunk_bounds(1000, None) == [(0, 1000)]


def test_oversized_chunk_collapses_to_one():
    assert chunk_bounds(1000, 5000) == [(0, 1000)]


def test_bounds_tile_the_whole_range_without_gaps_or_overlap():
    bounds = chunk_bounds(1000, 300)
    assert bounds[0][0] == 0 and bounds[-1][1] == 1000
    assert all(b[1] == c[0] for b, c in pairwise(bounds))
    assert sum(b - a for a, b in bounds) == 1000


def test_final_chunk_is_short_not_dropped():
    """1000 samples at 300/chunk leaves a 100-sample tail that must survive."""
    assert chunk_bounds(1000, 300) == [(0, 300), (300, 600), (600, 900), (900, 1000)]


# ---- round trip --------------------------------------------------------


@pytest.mark.parametrize("chunk_samples", [None, 3000, 1000, 999, 1])
def test_round_trip_is_exact_at_every_chunking(chunk_samples):
    ds, ad = _ds(), _adapter()
    buffers, _ = encode(ds, ad, chunk_samples=chunk_samples)
    out, _ = decode(buffers, ad, template=ds.data, chunk_samples=chunk_samples)
    np.testing.assert_array_equal(out, ds.data)


def test_chunk_count_matches_bounds():
    ds, ad = _ds(), _adapter()
    buffers, _ = encode(ds, ad, chunk_samples=1000)
    assert len(buffers) == 3


def test_decode_rejects_a_chunking_mismatch():
    """Silently decoding with different chunking would corrupt data."""
    ds, ad = _ds(), _adapter()
    buffers, _ = encode(ds, ad, chunk_samples=1000)
    with pytest.raises(ValueError, match="chunk count mismatch"):
        decode(buffers, ad, template=ds.data, chunk_samples=500)


def test_one_dimensional_input_round_trips():
    rng = np.random.default_rng(1)
    ds = LoadedDataset(
        data=rng.integers(-2000, 2000, size=3000).astype(np.int16), sample_rate_hz=1000.0
    )
    ad = _adapter()
    buffers, _ = encode(ds, ad, chunk_samples=1000)
    out, _ = decode(buffers, ad, template=ds.data, chunk_samples=1000)
    np.testing.assert_array_equal(out, ds.data)


# ---- the comparability claim ------------------------------------------


def test_smaller_chunks_compress_worse(tmp_path):
    """The reason this axis exists: chunking is not free, so a whole-buffer
    number cannot be compared against the paper's 1 s number."""
    npy = tmp_path / "x.npy"
    rng = np.random.default_rng(2)
    # Correlated signal so context genuinely helps the codec.
    sig = np.cumsum(rng.normal(0, 30, size=(30000, 8)), axis=0).astype(np.int16)
    np.save(npy, sig)
    spec = f"npy:path={npy},sample_rate_hz=30000"
    whole = run_cell(spec, "blosc-zstd", {"level": 9}, chunk_duration_s=None)
    chunked = run_cell(spec, "blosc-zstd", {"level": 9}, chunk_duration_s=0.01)
    assert chunked.metrics["cr"] < whole.metrics["cr"]
    assert chunked.metrics["n_chunks"] > whole.metrics["n_chunks"] == 1


def test_metrics_record_the_chunking_condition(tmp_path):
    npy = tmp_path / "x.npy"
    np.save(npy, np.zeros((3000, 4), dtype=np.int16))
    spec = f"npy:path={npy},sample_rate_hz=1000"
    m = run_cell(spec, "blosc-zstd", {}, chunk_duration_s=1.0).metrics
    assert m["chunk_duration_s"] == 1.0
    assert m["n_chunks"] == 3
    default = run_cell(spec, "blosc-zstd", {}).metrics
    assert default["chunk_duration_s"] is None
    assert default["n_chunks"] == 1


# ---- profile axis ------------------------------------------------------


def _profile(**over):
    raw = {
        "name": "t",
        "datasets": ["synthetic:duration_s=1.0"],
        "codecs": [{"codec": "lzma", "params": {"preset": 6}}],
    }
    raw.update(over)
    return load_profile(raw)


def test_default_cell_ids_are_unchanged_by_the_new_axis():
    """Adding the axis must not orphan existing results directories."""
    cells = list(expand_matrix(_profile()))
    assert [c.cell_id for c in cells] == ["synthetic__lzma-preset_6"]
    assert cells[0].chunk_duration_s is None


def test_chunk_axis_crosses_and_labels_cells():
    cells = list(expand_matrix(_profile(chunk_durations_s=[1.0, 0.1])))
    assert [c.cell_id for c in cells] == [
        "synthetic__lzma-preset_6-chunk1s",
        "synthetic__lzma-preset_6-chunk0.1s",
    ]
    assert [c.chunk_duration_s for c in cells] == [1.0, 0.1]


def test_null_can_be_swept_alongside_a_duration():
    cells = list(expand_matrix(_profile(chunk_durations_s=[None, 1.0])))
    assert [c.cell_id for c in cells] == [
        "synthetic__lzma-preset_6",
        "synthetic__lzma-preset_6-chunk1s",
    ]


@pytest.mark.parametrize(
    ("value", "match"),
    [
        ([], "non-empty list"),
        (1.0, "non-empty list"),
        ([0], "must be > 0"),
        ([-1.0], "must be > 0"),
        (["abc"], "must be a number or null"),
        ([1.0, 1.0], "duplicate entries"),
    ],
)
def test_chunk_axis_validation(value, match):
    with pytest.raises(ValueError, match=match):
        _profile(chunk_durations_s=value)


def test_codec_can_narrow_the_chunk_axis():
    """T.261 opts out of 1 s chunks: not in the paper, and one BWC process
    spawn per second of recording would dominate its runtime."""
    prof = _profile(
        chunk_durations_s=[None, 1.0],
        codecs=[
            {"codec": "lzma", "params": {"preset": 6}},
            {"codec": "blosc-zstd", "params": {}, "chunk_durations_s": [None]},
        ],
    )
    cells = list(expand_matrix(prof))
    lzma = [c for c in cells if c.codec == "lzma"]
    zstd = [c for c in cells if c.codec == "blosc-zstd"]
    assert sorted(c.chunk_duration_s or 0 for c in lzma) == [0, 1.0]
    assert [c.chunk_duration_s for c in zstd] == [None]


def test_per_codec_chunk_axis_is_validated_too():
    with pytest.raises(ValueError, match="must be > 0"):
        _profile(codecs=[{"codec": "lzma", "chunk_durations_s": [-1]}])
