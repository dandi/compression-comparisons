"""Abstract base for codec adapters."""

from __future__ import annotations

from typing import Any, ClassVar

import numpy as np
from numcodecs.abc import Codec


class CodecAdapter:
    """Wrap a `numcodecs.abc.Codec` with benchmark metadata.

    Subclasses set the class-level `name` (registry key) and `lossy` flag,
    then implement `__init__(**params)` and `make_codec()`.

    **Filters.** Buccino et al. compress through a Zarr array, and Zarr
    applies a `filters` list to each chunk *before* handing it to the
    compressor (`zarr.core.Array._encode_chunk`). The paper uses that hook
    for two axes we must reproduce:

    * `numcodecs.Shuffle(elementsize=2)` — its byte-shuffle for the
      non-blosc codecs. Table 2 lists `(no, byte)` for gzip / zlib / lzma /
      lz4 / zstd, and the effect is large: on NP2, `lz4` byte-shuffled
      compresses 1.55x better than unshuffled, and the paper's headline NP2
      LZMA figure is a byte-shuffled cell.
    * `numcodecs.Delta` / a 2-D delta — Fig 7(a)/(c), where a time-axis
      delta lifts NP1 blosc-zstd from 2.79 to 3.24.

    Adapters therefore carry an ordered filter list. `encode` applies them
    left-to-right then compresses; `decode` decompresses then inverts them
    right-to-left. blosc's own `shuffle=` argument is a different mechanism
    (internal to the blosc meta-compressor) and stays where it is.
    """

    name: ClassVar[str] = ""
    lossy: ClassVar[bool] = False

    def __init__(self, delta: str = "no", **params: Any) -> None:
        from compbench.codecs.filters import DELTA_VARIANTS

        if delta not in DELTA_VARIANTS:
            raise ValueError(f"delta must be one of {sorted(DELTA_VARIANTS)}; got {delta!r}")
        self._delta = delta
        self.params: dict[str, Any] = dict(params)
        if delta != "no":
            self.params["delta"] = delta

    def _delta_filters(self) -> list[Codec]:
        """The paper's Fig 7(a)/(c) delta axis, available to every codec."""
        from compbench.codecs.filters import make_delta_filter

        f = make_delta_filter(self._delta)
        return [] if f is None else [f]

    def make_codec(self) -> Codec:
        """Return a fresh `numcodecs.abc.Codec` instance."""
        raise NotImplementedError

    def make_filters(self) -> list[Codec]:
        """Ordered pre-compression filters.

        Delta first, then any adapter-specific filter (the byte shuffle):
        differencing decorrelates, and shuffling the residuals groups their
        high bytes together. Zarr applies a `filters` list in order, so this
        ordering is the thing that gets recorded and must be reproduced.
        """
        return self._delta_filters()

    def encode_chunk(self, chunk: np.ndarray) -> bytes:
        """Filters (in order) then the compressor — Zarr's chunk pipeline."""
        buf: Any = chunk
        for f in self.make_filters():
            buf = f.encode(buf)
        return bytes(self.make_codec().encode(buf))

    def decode_chunk(self, data: bytes, template: np.ndarray) -> np.ndarray:
        """The inverse: decompress, then invert filters in reverse order.

        `template` fixes the dtype and shape that the filter chain must
        restore; numcodecs codecs carry no shape metadata of their own.
        """
        buf: Any = self.make_codec().decode(data)
        for f in reversed(self.make_filters()):
            # A filter that differences along an explicit axis needs the
            # chunk's 2-D shape back first; numcodecs codecs return flat
            # buffers carrying no shape metadata.
            if getattr(f, "needs_shape", False):
                raw = buf.tobytes() if isinstance(buf, np.ndarray) else bytes(buf)
                buf = np.frombuffer(raw, dtype=template.dtype).reshape(template.shape)
            buf = f.decode(buf)
        raw = buf.tobytes() if isinstance(buf, np.ndarray) else bytes(buf)
        return np.frombuffer(raw, dtype=template.dtype).reshape(template.shape)

    def describe(self) -> dict[str, Any]:
        """Machine-readable description used in manifests and reports."""
        desc: dict[str, Any] = {
            "name": self.name,
            "lossy": self.lossy,
            "params": self.params,
        }
        filters = self.make_filters()
        if filters:
            # Recorded because a filter changes the bytes without changing
            # the codec name — exactly the kind of condition that silently
            # makes two cells incomparable.
            desc["filters"] = [f.get_config() for f in filters]
        return desc
