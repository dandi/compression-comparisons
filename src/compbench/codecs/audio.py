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
              to `config.flags |= CONFIG_HYBRID_FLAG` in upstream commit
              a812cb67 ("Test multi-threading"), which shipped in **0.1.4**
              — not 0.2.3, as this comment previously said. There is no
              changelog entry; the fix rode along inside a threading commit.

              What the plain `=` destroyed is mostly NOT the level flags.
              Four statements earlier the same function sets
              `config.flags = CONFIG_PAIR_UNDEF_CHANS`, and only levels 1, 3
              and 4 `|=` a level bit — **level 2 sets no bit at all**. Our
              profiles run `level: 2`, so for our cells the single flag
              difference is `CONFIG_PAIR_UNDEF_CHANS` (0x20000000). Verified
              empirically: at level 2 and level 3, 0.1.3 emits bit-identical
              output, i.e. it silently discards `level` in hybrid mode. The
              paper's own lossy driver passed `level=3`, which therefore
              never took effect.

              Measured consequence, 4 paired recordings x 7 bps: the two
              versions are rate-distortion equivalent at matched CR (median
              +1.2 %). But on ABSOLUTE CR against the paper's published
              table, 0.1.3 reproduces to within 0.9 % at all 28 points while
              0.2.3 deviates by up to 7.8 %. Recorded in the manifest via
              `wavpack_numcodecs_version` so the lossy rows carry it.
            """
            from wavpack_numcodecs import WavPack

            return WavPack(level=self._level, bps=self._bps, num_decoding_threads=1)

        def describe(self) -> dict[str, object]:
            desc = super().describe()
            desc["wavpack_numcodecs_version"] = getattr(wavpack_numcodecs, "__version__", "unknown")
            # The paper used 0.1.3, whose hybrid mode discards the level
            # flags; see make_codec.
            desc["hybrid_flag_semantics"] = (
                "or-equals (>=0.1.4)" if self._bps is not None else "n/a"
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
