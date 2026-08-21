"""Bit truncation — Buccino et al.'s lossy baseline (paper §2.4.1, Figs 10-14).

Discards the N least-significant bits of each sample, then compresses the
reduced-entropy result losslessly. It is the paper's foil for WavPack
Hybrid, and the reason it matters to us is that **it is the arm that
breaks**: on NP1 it goes from indistinguishable-from-lossless at 4 bits to
destroyed at 5 (false positives 65 -> 1435, accuracy 0.998 -> 0.927), and
on NP2 at 7 bits instead of 5, consistent with its 4x finer voltage
resolution.

That makes it a positive control for the measuring apparatus. A pipeline
that reports "no effect" for every lossy setting is indistinguishable from
a correct one unless something in the sweep is known to break. If our
sorting metrics do not show the collapse at NP1/5, the metrics are wrong.

Faithfulness notes, all verified against `ephys-compression/utils.py`:

* It is **round-half-to-even**, not an arithmetic right shift. The paper's
  prose says "right-shifting", but the code is
  ``FixedScaleOffset(offset=0, scale=1/2**bits)``, whose encode does
  ``np.around((arr - offset) * scale)``. A shift floors and is asymmetric
  about zero; rounding is not. Measured at N=1: 1->0, 3->2, 5->2, 7->4.
* The encoded array stays **int16** — all the compression gain comes from
  the base codec seeing reduced entropy, not from a narrower dtype.
* The base codec is ``Blosc(cname="zstd", clevel=9, shuffle=BITSHUFFLE)``.
* ``bits == 0`` returns **no filter at all**, not a scale-1.0 filter, so
  the zero cell is genuinely lossless and serves as the anchor.
"""

from __future__ import annotations

from typing import Any, ClassVar

import numpy as np
from numcodecs import Blosc, FixedScaleOffset
from numcodecs.abc import Codec

from compbench.codecs import register
from compbench.codecs.base import CodecAdapter


@register
class BitTruncAdapter(CodecAdapter):
    """`bittrunc` — truncate `bits` LSBs, then blosc-zstd/bitshuffle."""

    name: ClassVar[str] = "bittrunc"

    def __init__(self, bits: int | str = 0, delta: str = "no") -> None:
        b = int(bits)
        if not 0 <= b <= 15:
            raise ValueError(f"bits must be in 0..15; got {b}")
        if delta != "no":
            raise ValueError(
                "the paper never combines bit truncation with a delta filter; "
                "the two are separate axes"
            )
        super().__init__(bits=b, delta=delta)
        self._bits = b

    @property
    def lossy(self) -> bool:  # type: ignore[override]
        # bits=0 is the lossless anchor; run_cell asserts byte-exactness on it.
        return self._bits > 0

    def make_codec(self) -> Codec:
        return Blosc(cname="zstd", clevel=9, shuffle=Blosc.BITSHUFFLE)

    def make_filters(self) -> list[Codec]:
        if self._bits == 0:
            return []
        return [FixedScaleOffset(offset=0, scale=1.0 / 2**self._bits, dtype="i2")]

    def encode_chunk(self, chunk: np.ndarray) -> bytes:
        """Guard the one way this codec can silently corrupt data.

        `FixedScaleOffset.decode` computes ``enc / scale`` in float and casts
        back, which **wraps** rather than saturating: at bits=1 a sample of
        32767 encodes to 16384 and decodes to 32768, i.e. -32768. Ephys data
        sits near +/-1000 counts so this never fires in practice, but a
        silent sign flip is not something to leave to practice.
        """
        if self._bits and np.issubdtype(chunk.dtype, np.integer):
            info = np.iinfo(chunk.dtype)
            limit = info.max - 2 ** (self._bits - 1)
            peak = int(np.abs(chunk).max()) if chunk.size else 0
            if peak > limit:
                raise ValueError(
                    f"bittrunc(bits={self._bits}): input peak {peak} exceeds {limit}, "
                    f"so decoding would overflow {chunk.dtype} and wrap sign. "
                    f"Use fewer bits or a wider dtype."
                )
        return super().encode_chunk(chunk)

    def describe(self) -> dict[str, Any]:
        desc = super().describe()
        desc["base_codec"] = {"cname": "zstd", "clevel": 9, "shuffle": "bitshuffle"}
        desc["rounding"] = "half-to-even (numcodecs FixedScaleOffset), NOT a right shift"
        return desc
