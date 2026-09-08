"""H5 — band splitting: code the LFP and spike bands at independent QP.

WHY THIS NEEDS CODE AT ALL. Every other hypothesis in the profile search is a
`.cfg` edit, because BWC exposes a wide parameter surface. It exposes no
frequency-weighting knob of any kind: the full stock preset
(`configs/bwc-cfg/r0-stock.cfg`) has no band, subband or spectral parameter,
so the encoder cannot be told "spend bits below 1 kHz". Splitting the signal
before it reaches the encoder is the only route to shaped error, which is why
the plan calls H5 exactly that.

WHY SHAPED ERROR IS THE POINT. Six hypotheses have now been tested and none
produced a usable win, because they all changed *how much* error the codec
makes and the distortion is pinned at the uniform-quantiser bound
(`rmse = QP/sqrt(12)` holds to 0.91-1.06x). What sorting responds to is
*where* the error lands: H8 delivered identical rate and distortion and still
cost 15 false positives at QP 3.0. Spike sorting bandpasses to 300-6000 Hz
before it does anything, so every bit T.261 spends below 300 Hz is invisible
to the sorter — and roughly 50 % of spike-discriminative energy is below
1 kHz with 80 % below 1.33 kHz, so the 300-6000 Hz band is about twice as
wide as the informative one.

RECONSTRUCTION IS EXACT BY CONSTRUCTION. The low band is rounded to integers
first and the high band is then defined as the *integer* residual
`hi = x - lo_i`, so `lo_i + hi == x` bit-exactly regardless of the filter.
A complementary-filter split computed in floating point would leave a
~1 ADU reconstruction floor and quietly cap achievable fidelity; defining the
residual against the already-rounded low band avoids that entirely. With both
bands coded losslessly this codec is therefore lossless, which is the null
control that makes the lossy numbers believable.

SAMPLE RATE IS DEMANDED, NOT DEFAULTED. A physical cutoff needs `fs`, and the
codec has no access to the recording. MEArec runs at 32 kHz while the real
IBL/AIND recordings are 30 kHz, so a numeric default would silently place the
crossover ~7 % wrong on one substrate or the other — invisible in every
metric we collect. The adapter still has to satisfy `cls()`, because
`codecs.all_adapters()` constructs every adapter generically, so `fs`
defaults to `None` and `make_codec()` refuses rather than guessing.
"""

from __future__ import annotations

import struct
from typing import Any, ClassVar

import numpy as np
from numcodecs.abc import Codec
from numcodecs.registry import register_codec

from compbench.codecs import register
from compbench.codecs.base import CodecAdapter
from compbench.codecs.t261 import _AVAILABLE as _BWC_AVAILABLE

_MAGIC = b"CBS1"
# magic + n_lo_bytes + n_hi_bytes + n_samples + n_channels
_HEADER = struct.Struct("<4sIIII")


def split_bands(
    x: np.ndarray, sample_rate_hz: float, split_hz: float, order: int = 4
) -> tuple[np.ndarray, np.ndarray]:
    """Split int16 `x` (n_samples, n_channels) into (low, high) int16 bands.

    `low + high == x` exactly. Zero-phase (`sosfiltfilt`) so the split adds
    no group delay that would shift spike times between the bands.
    """
    from scipy.signal import butter, sosfiltfilt

    if x.ndim == 1:
        x = x[:, None]
    nyq = sample_rate_hz / 2.0
    if not 0.0 < split_hz < nyq:
        raise ValueError(f"split_hz must be in (0, {nyq}); got {split_hz}")
    sos = butter(order, split_hz, btype="low", fs=sample_rate_hz, output="sos")
    lo_f = sosfiltfilt(sos, x.astype(np.float64), axis=0)
    lo = np.rint(lo_f)
    info = np.iinfo(np.int16)
    if lo.min() < info.min or lo.max() > info.max:
        raise ValueError(
            f"low band overflows int16 (range {lo.min()}..{lo.max()}); "
            "the input is not a plain int16 recording"
        )
    lo_i = lo.astype(np.int16)
    hi = x.astype(np.int32) - lo_i.astype(np.int32)
    if hi.min() < info.min or hi.max() > info.max:
        raise ValueError(
            f"high band overflows int16 (range {hi.min()}..{hi.max()}); "
            f"raise split_hz or lower the filter order (currently {order})"
        )
    return lo_i, np.ascontiguousarray(hi.astype(np.int16))


class T261BandSplitCodec(Codec):
    """Two T.261 encodes, one per band, in a single bitstream."""

    codec_id = "compbench-t261-bandsplit"

    def __init__(
        self,
        sample_rate_hz: float,
        split_hz: float = 300.0,
        qp_lo: float | None = None,
        qp_hi: float | None = None,
        preset: str = "r0-stock",
        order: int = 4,
        bit_depth: int = 16,
    ) -> None:
        self.sample_rate_hz = float(sample_rate_hz)
        self.split_hz = float(split_hz)
        self.qp_lo = None if qp_lo is None else float(qp_lo)
        self.qp_hi = None if qp_hi is None else float(qp_hi)
        self.preset = preset
        self.order = int(order)
        self.bit_depth = int(bit_depth)

    def _band_codec(self, qp: float | None) -> Codec:
        from compbench.codecs.t261 import T261Codec

        return T261Codec(
            preset=self.preset, bit_depth=self.bit_depth, step_size_for_qp=qp
        )

    def encode(self, buf: Any) -> bytes:
        x = np.ascontiguousarray(np.asarray(buf))
        if x.dtype != np.int16:
            raise TypeError(f"expected int16 input; got {x.dtype}")
        x2 = x[:, None] if x.ndim == 1 else x
        lo, hi = split_bands(x2, self.sample_rate_hz, self.split_hz, self.order)
        b_lo = bytes(self._band_codec(self.qp_lo).encode(lo))
        b_hi = bytes(self._band_codec(self.qp_hi).encode(hi))
        head = _HEADER.pack(_MAGIC, len(b_lo), len(b_hi), x2.shape[0], x2.shape[1])
        return head + b_lo + b_hi

    def decode(self, buf: Any, out: np.ndarray | None = None) -> np.ndarray:
        raw = bytes(buf)
        magic, n_lo, n_hi, n_samp, n_ch = _HEADER.unpack_from(raw, 0)
        if magic != _MAGIC:
            raise ValueError(f"not a band-split bitstream (magic {magic!r})")
        off = _HEADER.size
        b_lo = raw[off : off + n_lo]
        b_hi = raw[off + n_lo : off + n_lo + n_hi]
        shape = (n_samp, n_ch)
        lo = np.frombuffer(
            self._band_codec(self.qp_lo).decode(b_lo), dtype=np.int16
        ).reshape(shape)
        hi = np.frombuffer(
            self._band_codec(self.qp_hi).decode(b_hi), dtype=np.int16
        ).reshape(shape)
        # Sum in int32 then clip: each band is independently quantised, so
        # their sum can exceed int16 at the extremes even though the original
        # did not. Clipping is the honest reconstruction — wrapping would turn
        # a small quantisation error into a full-scale spike.
        total = np.clip(
            lo.astype(np.int32) + hi.astype(np.int32),
            np.iinfo(np.int16).min,
            np.iinfo(np.int16).max,
        ).astype(np.int16)
        if out is not None:
            out_arr = np.asarray(out)
            out_arr.reshape(shape)[...] = total
            return out_arr
        return total

    def get_config(self) -> dict[str, Any]:
        return {
            "id": self.codec_id,
            "sample_rate_hz": self.sample_rate_hz,
            "split_hz": self.split_hz,
            "qp_lo": self.qp_lo,
            "qp_hi": self.qp_hi,
            "preset": self.preset,
            "order": self.order,
            "bit_depth": self.bit_depth,
        }


if _BWC_AVAILABLE:
    register_codec(T261BandSplitCodec)


class T261BandSplitAdapter(CodecAdapter):
    """T.261 with the LFP and spike bands coded at independent QP (H5)."""

    name: ClassVar[str] = "t261-bandsplit"

    def __init__(
        self,
        sample_rate_hz: float | str | None = None,
        split_hz: float | str = 300.0,
        qp_lo: float | str | None = None,
        qp_hi: float | str | None = None,
        preset: str = "r0-stock",
        order: int | str = 4,
        bit_depth: int | str = 16,
        **kw: Any,
    ) -> None:
        def _f(v: Any) -> float | None:
            return None if v in (None, "", "None") else float(v)

        # Defaulted to None rather than to a number, deliberately. Adapters
        # must satisfy `cls()` (`codecs.all_adapters()` constructs them
        # generically), but a numeric default would place the crossover ~7 %
        # wrong whenever the substrate is not that rate -- MEArec is 32 kHz,
        # IBL/AIND are 30 kHz -- and nothing we measure would reveal it. So
        # construction succeeds and `make_codec()` refuses instead.
        self._fs = None if sample_rate_hz in (None, "", "None") else float(sample_rate_hz)
        self._split_hz = float(split_hz)
        self._qp_lo = _f(qp_lo)
        self._qp_hi = _f(qp_hi)
        self._preset = preset
        self._order = int(order)
        self._bit_depth = int(bit_depth)
        super().__init__(
            sample_rate_hz=self._fs,
            split_hz=self._split_hz,
            qp_lo=self._qp_lo,
            qp_hi=self._qp_hi,
            preset=preset,
            order=self._order,
            bit_depth=self._bit_depth,
            **kw,
        )

    @property
    def lossy(self) -> bool:  # type: ignore[override]
        """Lossy if either band is quantised.

        The split itself is exact (`lo + hi == x`), so losslessness is decided
        by the two QPs alone — same rule as `T261Adapter`, applied per band.
        """
        for qp in (self._qp_lo, self._qp_hi):
            if qp is not None and qp > 1.0:
                return True
        return "_lossless" not in self._preset

    def make_codec(self) -> Codec:
        if self._fs is None:
            raise ValueError(
                "t261-bandsplit requires sample_rate_hz: the crossover is a "
                "physical frequency and the codec cannot see the recording. "
                "Pass e.g. sample_rate_hz=30000 (IBL/AIND) or 32000 (MEArec)."
            )
        return T261BandSplitCodec(
            sample_rate_hz=self._fs,
            split_hz=self._split_hz,
            qp_lo=self._qp_lo,
            qp_hi=self._qp_hi,
            preset=self._preset,
            order=self._order,
            bit_depth=self._bit_depth,
        )

    def describe(self) -> dict[str, Any]:
        from compbench.codecs.t261 import (
            _bwc_encoder_version,
            _bwc_git_sha,
            _cfg_sha256,
        )

        info = super().describe()
        info["bwc"] = {
            "bwc_git_sha": _bwc_git_sha(),
            "encoder_version": _bwc_encoder_version(),
            "cfg_sha256": _cfg_sha256(self._preset),
        }
        return info


if _BWC_AVAILABLE:
    # Registered only alongside the plain T.261 adapter: this codec is two
    # T.261 encodes in a trench coat and cannot work without the binaries.
    register(T261BandSplitAdapter)
