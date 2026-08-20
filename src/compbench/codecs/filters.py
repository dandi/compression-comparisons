"""Zarr-style pre-compression filters — the paper's Fig 7(a)/(c) delta axis.

Buccino et al. sweep four delta variants as Zarr `filters` ahead of the
compressor (`scripts/benchmark-lossless-delta.py`):

    no · 1d · 2d-time · 2d-space · 2d-time-space

It is a headline result, not a footnote: a time-axis delta lifts NP1
blosc-zstd from 2.79 to 3.24 (paper §3.1.6), closing much of the gap to the
audio codecs — at the cost of decompression speed, which is why the paper
ultimately does not recommend it.

`numcodecs.Delta` only differences a flat buffer, which on a
(samples, channels) chunk is a *time* delta only by accident of C ordering
and is wrong across the row boundary. These filters difference along an
explicit axis instead.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from numcodecs.abc import Codec


class Delta2D(Codec):  # type: ignore[misc]  # numcodecs ships no stubs
    """Difference along one axis of a 2-D chunk, or along both in sequence.

    ``axis=0`` is the time delta (each sample minus the previous sample on
    the same channel); ``axis=1`` is the space delta (each channel minus its
    neighbour at the same instant); ``axis="both"`` applies time then space,
    matching the paper's ``2d-time-space``.

    Encoding keeps the leading row/column intact so the transform is exactly
    invertible in the input dtype. Arithmetic is done in the input's own
    integer type, which wraps on overflow — and wrapping is what makes it
    lossless, since the inverse cumulative sum wraps identically.
    """

    codec_id = "compbench.delta2d"

    #: Decoding needs the chunk's 2-D shape restored first — numcodecs codecs
    #: return flat buffers with no shape metadata, and differencing along
    #: axis 1 is meaningless on a flattened array.
    needs_shape = True

    def __init__(self, axis: int | str = 0, dtype: Any = "i2") -> None:
        if axis not in (0, 1, "both"):
            raise ValueError(f"axis must be 0, 1, or 'both'; got {axis!r}")
        self.axis = axis
        self.dtype = np.dtype(dtype)

    def _axes(self) -> tuple[int, ...]:
        return (0, 1) if self.axis == "both" else (int(self.axis),)

    def encode(self, buf: Any) -> np.ndarray:
        arr = np.ascontiguousarray(buf, dtype=self.dtype)
        if arr.ndim != 2:
            raise ValueError(f"Delta2D expects a 2-D chunk; got shape {arr.shape}")
        out = arr.copy()
        for ax in self._axes():
            # np.diff in the array's own dtype: wraps, and the inverse
            # cumsum wraps back to the identical value.
            d = np.diff(out, axis=ax)
            if ax == 0:
                out = np.concatenate([out[:1, :], d], axis=0)
            else:
                out = np.concatenate([out[:, :1], d], axis=1)
        return out

    def decode(self, buf: Any, out: Any = None) -> np.ndarray:
        arr = np.frombuffer(buf, dtype=self.dtype) if isinstance(buf, bytes) else np.asarray(buf)
        arr = arr.astype(self.dtype, copy=True)
        for ax in reversed(self._axes()):
            arr = np.cumsum(arr, axis=ax, dtype=self.dtype).astype(self.dtype, copy=False)
        if out is not None:
            out[...] = arr
            return np.asarray(out)
        return np.asarray(arr)

    def get_config(self) -> dict[str, Any]:
        return {"id": self.codec_id, "axis": self.axis, "dtype": self.dtype.str}


def make_delta_filter(variant: str, dtype: Any = "i2") -> Codec | None:
    """Build the paper's delta filter for one variant label.

    ``1d`` is deliberately NOT ``Delta2D(axis=0)``. The paper uses
    ``numcodecs.Delta``, which differences the *flattened* chunk — so on a
    C-ordered (samples, channels) array it differences along the channel
    axis and wraps at every row boundary. That is why it makes compression
    *worse*: on CSHZAD026 the paper measures blosc-zstd 2.445 with ``1d``
    against ~2.53 with none, while the true time delta (``2d-time``) gives
    3.283. Mapping ``1d`` onto a time delta would have silently turned a
    known-bad condition into the best one.
    """
    if variant not in DELTA_VARIANTS:
        raise ValueError(f"delta must be one of {list(DELTA_VARIANTS)}; got {variant!r}")
    if variant == "no":
        return None
    if variant == "1d":
        from numcodecs import Delta

        return Delta(dtype=dtype)
    return Delta2D(dtype=dtype, **_DELTA_2D_KWARGS[variant])


_DELTA_2D_KWARGS: dict[str, dict[str, Any]] = {
    "2d-time": {"axis": 0},
    "2d-space": {"axis": 1},
    "2d-time-space": {"axis": "both"},
}

#: Paper labels. `no` is the absence of a filter, not a no-op filter,
#: matching the driver's ``{"no": []}``.
DELTA_VARIANTS: tuple[str, ...] = ("no", "1d", "2d-time", "2d-space", "2d-time-space")
