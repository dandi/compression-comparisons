"""Audio-codec adapters — FLAC and WavPack.

Both packages are separate from `numcodecs` core:
- `wavpack-numcodecs` (PyPI) — the same package used by the Buccino et al.
  paper's implementation, published from AllenNeuralDynamics.
- `flac-numcodecs` (PyPI) — community wrapper for libFLAC.

If either is missing at import time, the corresponding adapter simply isn't
registered (see `compbench.codecs.__init__`'s try/except).
"""

from __future__ import annotations

from typing import ClassVar

from numcodecs.abc import Codec

from compbench.codecs import register
from compbench.codecs.base import CodecAdapter

try:
    import wavpack_numcodecs
except ImportError:
    pass  # `wavpack` adapter simply not registered.
else:

    @register
    class WavPackAdapter(CodecAdapter):
        """WavPack — audio codec; lossless by default, `bps` triggers hybrid mode."""

        name: ClassVar[str] = "wavpack"

        def __init__(
            self,
            level: int | str = 2,
            bps: float | str | None = None,
            delta: str = "no",
        ) -> None:
            bps_num = float(bps) if bps not in (None, "", "None") else None
            super().__init__(level=int(level), bps=bps_num, delta=delta)
            self._level = int(level)
            self._bps = bps_num

        @property
        def lossy(self) -> bool:  # type: ignore[override]
            return self._bps is not None

        def make_codec(self) -> Codec:
            """Construct the WavPack codec, pinned to single-threaded decode.

            Two version differences from the 0.1.3 the paper used:

            * 0.2.3 defaults `num_decoding_threads=8`; 0.1.3 had no threading
              at all. Left at the default our decode speed would be ~8x the
              paper's for reasons that have nothing to do with the codec.
              Pinned to 1 for the same reason blosc is (see codecs/blosc.py).
            * The hybrid path changed from `config.flags = CONFIG_HYBRID_FLAG`
              (which DISCARDS the level flags) to `config.flags |=
              CONFIG_HYBRID_FLAG` (which KEEPS them). So at a given `bps`,
              0.2.3 at `level=3` emits a different bitstream than 0.1.3 did:
              ours runs in high mode, the paper's ran in default mode. This
              is not correctable from here — it is recorded in the manifest
              via `wavpack_numcodecs_version` so the lossy rows carry the
              caveat with them.
            """
            from wavpack_numcodecs import WavPack

            return WavPack(level=self._level, bps=self._bps, num_decoding_threads=1)

        def describe(self) -> dict[str, object]:
            desc = super().describe()
            desc["wavpack_numcodecs_version"] = getattr(wavpack_numcodecs, "__version__", "unknown")
            # The paper used 0.1.3, whose hybrid mode discards the level
            # flags; see make_codec.
            desc["hybrid_flag_semantics"] = (
                "or-equals (>=0.2.0)" if self._bps is not None else "n/a"
            )
            return desc


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

        def __init__(self, level: int | str = 5, delta: str = "no") -> None:
            super().__init__(level=int(level), delta=delta)
            self._level = int(level)

        def make_codec(self) -> Codec:
            from flac_numcodecs import Flac

            return Flac(level=self._level)
