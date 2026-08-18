"""Audio-codec adapters — FLAC and WavPack.

Both packages are separate from `numcodecs` core:
- `wavpack-numcodecs` (PyPI) — the same package used by the Buccino et al.
  paper's implementation, published from AllenNeuralDynamics.
- `flac-numcodecs` (PyPI) — community wrapper for libFLAC.

If either is missing at import time, the corresponding adapter simply isn't
registered (see `compbench.codecs.__init__`'s try/except).
"""

from __future__ import annotations

from typing import Any, ClassVar

from numcodecs.abc import Codec

from compbench.codecs import register
from compbench.codecs.base import CodecAdapter

try:
    import wavpack_numcodecs  # noqa: F401
except ImportError:
    pass  # `wavpack` adapter simply not registered.
else:

    @register
    class WavPackAdapter(CodecAdapter):
        """WavPack — audio codec; lossless by default, `bps` triggers hybrid mode."""

        name: ClassVar[str] = "wavpack"

        def __init__(self, level: int | str = 2, bps: float | str | None = None, **kw: Any) -> None:
            bps_num = float(bps) if bps not in (None, "", "None") else None
            super().__init__(level=int(level), bps=bps_num, **kw)
            self._level = int(level)
            self._bps = bps_num

        @property
        def lossy(self) -> bool:  # type: ignore[override]
            return self._bps is not None

        def make_codec(self) -> Codec:
            from wavpack_numcodecs import WavPack

            return WavPack(level=self._level, bps=self._bps)


try:
    import flac_numcodecs  # noqa: F401
except ImportError:
    pass  # FLAC adapter simply not registered.
else:

    @register
    class FlacAdapter(CodecAdapter):
        """FLAC — audio codec; strictly lossless."""

        name: ClassVar[str] = "flac"
        lossy: ClassVar[bool] = False

        def __init__(self, level: int | str = 5, **kw: Any) -> None:
            super().__init__(level=int(level), **kw)
            self._level = int(level)

        def make_codec(self) -> Codec:
            from flac_numcodecs import Flac

            return Flac(level=self._level)
