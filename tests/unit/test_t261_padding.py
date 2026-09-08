"""Chunk padding: the ragged final block is coded pathologically.

A chunk whose length is not a multiple of the max block size leaves a
remainder that BWC extends by REPLICATING the last sample. That appends a DC
step, the final block becomes half signal and half constant, and the DCT
dumps the resulting error onto the real samples. Measured on 1 s of MEArec
NP1 at QP 5.0, max block 1024 (remainder 256):

    extension      max|e|  n>2QP  tail rmse  body rmse
    unpadded           18    488     3.4956     1.4202
    replicate          18    488     3.4956     1.4202
    mirror              8      0     1.4186     1.4202
    zero               18    536     3.5166     1.4202

Replicating externally is bit-identical to not padding, which is how we know
BWC does it internally. Mirroring removes the discontinuity and the tail then
matches the body exactly.

These tests pin the padding arithmetic and the round-trip, which need no BWC
binaries; the encoder-side numbers above are recorded in the codec source.
"""

from __future__ import annotations

import numpy as np
import pytest


def _pad_like_codec(x, block):
    """Mirror the codec's padding arithmetic (see T261Codec.encode)."""
    rem = x.shape[0] % block
    if not rem:
        return x, 0
    pad = block - rem
    return np.pad(x, ((0, pad), (0, 0)), mode="symmetric"), pad


def test_padding_reaches_a_block_multiple():
    for n in (32000, 30000, 1, 1023, 1025, 300000):
        x = np.zeros((n, 4), dtype=np.int16)
        padded, pad = _pad_like_codec(x, 1024)
        assert padded.shape[0] % 1024 == 0, f"n={n} not aligned after padding"
        assert padded.shape[0] == n + pad


def test_padding_works_when_pad_exceeds_input_length():
    """A short final chunk needs more padding than it has samples.

    A reverse-slice implementation silently produces too few samples here and
    leaves the length unaligned, which is exactly the bug this guards.
    """
    x = np.arange(10, dtype=np.int16)[:, None]
    padded, pad = _pad_like_codec(x, 1024)
    assert pad == 1014
    assert padded.shape[0] == 1024


def test_padding_preserves_the_real_samples():
    rng = np.random.default_rng(0)
    x = rng.integers(-500, 500, size=(32000, 3)).astype(np.int16)
    padded, pad = _pad_like_codec(x, 1024)
    assert np.array_equal(padded[: x.shape[0]], x)


def test_no_padding_when_already_aligned():
    x = np.zeros((2048, 4), dtype=np.int16)
    padded, pad = _pad_like_codec(x, 1024)
    assert pad == 0 and padded.shape == x.shape


def test_mirror_extension_has_no_step_at_the_boundary():
    """The mechanism: replication appends a DC step, mirroring does not.

    A ramp makes this visible — replicating holds the final value flat, while
    mirroring continues with the reversed slope.
    """
    x = np.arange(0, 2000, dtype=np.int16)[:, None]
    padded, pad = _pad_like_codec(x, 1024)
    ext = padded[2000:, 0].astype(int)
    assert len(ext) == pad
    # replication would give a constant; mirroring descends from the edge
    assert len(np.unique(ext)) > 1, "extension is constant — not mirrored"
    assert ext[0] == 1999 and ext[1] == 1998, "not a symmetric reflection"


def test_codec_round_trip_is_exact_through_the_padding_path():
    """Padding adds a length header and a trim; an off-by-one there would
    corrupt every result silently."""
    from compbench.codecs import names

    if "t261" not in names():
        pytest.skip("BWC binaries unavailable")
    from compbench.codecs.t261 import T261Codec

    rng = np.random.default_rng(1)
    x = np.ascontiguousarray(rng.integers(-300, 300, size=(3000, 4)).astype(np.int16))
    c = T261Codec(preset="combinedPresetEEG_IndepChannel_lossless", pad_to_block=1024)
    enc = bytes(c.encode(x))
    dec = np.asarray(c.decode(enc)).reshape(x.shape)
    assert dec.shape == x.shape
    assert np.array_equal(dec, x), "padded lossless round-trip was not exact"


def test_unpadded_streams_still_decode():
    """`pad_to_block=0` must produce a stream with no header, so existing
    results stay byte-comparable."""
    from compbench.codecs import names

    if "t261" not in names():
        pytest.skip("BWC binaries unavailable")
    from compbench.codecs.t261 import _PAD_MAGIC, T261Codec

    rng = np.random.default_rng(2)
    x = np.ascontiguousarray(rng.integers(-300, 300, size=(2048, 4)).astype(np.int16))
    c = T261Codec(preset="combinedPresetEEG_IndepChannel_lossless")
    enc = bytes(c.encode(x))
    assert enc[: len(_PAD_MAGIC)] != _PAD_MAGIC
    assert np.array_equal(np.asarray(c.decode(enc)).reshape(x.shape), x)
