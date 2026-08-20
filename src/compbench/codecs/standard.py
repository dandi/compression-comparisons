"""Single-library codec adapters — thin wrappers around `numcodecs` classes
for the general-purpose compressors evaluated in Buccino et al. Fig 2.
"""

from __future__ import annotations

from typing import ClassVar

from numcodecs import LZ4, LZMA, GZip, Shuffle, Zlib, Zstd
from numcodecs.abc import Codec

from compbench.codecs import register
from compbench.codecs.base import CodecAdapter

# Buccino et al. table 2 gives the non-blosc codecs a `(no, byte)` shuffle
# axis, applied as a Zarr *filter* rather than inside the codec:
#     shuffles["numcodecs"] = {"no": [], "byte": [Shuffle(2)]}   # int16 -> 2 bytes
# It is not a minor axis. Median CR over the 8 sessions at the paper's
# `high` level, byte vs no: NP2 lz4 1.55x, NP2 gzip/zlib 1.25x, NP1
# gzip/zlib 1.08x — and the paper's own headline NP2 LZMA number (1.91) is
# a byte-shuffled cell.
_SHUFFLE_CHOICES = ("no", "byte")


class _ShuffleMixin(CodecAdapter):
    """Adds the paper's `(no, byte)` Zarr-filter shuffle axis."""

    def _init_shuffle(self, shuffle: str, elementsize: int = 2) -> None:
        if shuffle not in _SHUFFLE_CHOICES:
            raise ValueError(
                f"shuffle must be one of {list(_SHUFFLE_CHOICES)}; got {shuffle!r}. "
                f"(blosc codecs additionally accept 'bit' — that is blosc's own "
                f"internal shuffle, a different mechanism.)"
            )
        self._shuffle = shuffle
        self._elementsize = int(elementsize)

    def make_filters(self) -> list[Codec]:
        # elementsize=2 because the benchmark data is int16; the paper
        # hardcodes 2 for the same reason. Delta (from the base) runs first.
        shuffle = [Shuffle(elementsize=self._elementsize)] if self._shuffle == "byte" else []
        return self._delta_filters() + shuffle


@register
class GZipAdapter(_ShuffleMixin):
    """Gzip framing over deflate (Python `zlib` + gzip header)."""

    name: ClassVar[str] = "gzip"
    lossy: ClassVar[bool] = False

    def __init__(self, level: int | str = 5, shuffle: str = "no", delta: str = "no") -> None:
        super().__init__(level=int(level), shuffle=shuffle, delta=delta)
        self._level = int(level)
        self._init_shuffle(shuffle)

    def make_codec(self) -> Codec:
        return GZip(level=self._level)


@register
class ZlibAdapter(_ShuffleMixin):
    """Raw deflate (no gzip framing)."""

    name: ClassVar[str] = "zlib"
    lossy: ClassVar[bool] = False

    def __init__(self, level: int | str = 5, shuffle: str = "no", delta: str = "no") -> None:
        super().__init__(level=int(level), shuffle=shuffle, delta=delta)
        self._level = int(level)
        self._init_shuffle(shuffle)

    def make_codec(self) -> Codec:
        return Zlib(level=self._level)


@register
class LZ4Adapter(_ShuffleMixin):
    """Raw LZ4 (no blosc framing)."""

    name: ClassVar[str] = "lz4"
    lossy: ClassVar[bool] = False

    def __init__(self, acceleration: int | str = 1, shuffle: str = "no", delta: str = "no") -> None:
        super().__init__(acceleration=int(acceleration), shuffle=shuffle, delta=delta)
        self._acceleration = int(acceleration)
        self._init_shuffle(shuffle)

    def make_codec(self) -> Codec:
        return LZ4(acceleration=self._acceleration)


@register
class ZstdAdapter(_ShuffleMixin):
    """Raw Zstandard (no blosc framing)."""

    name: ClassVar[str] = "zstd"
    lossy: ClassVar[bool] = False

    def __init__(self, level: int | str = 3, shuffle: str = "no", delta: str = "no") -> None:
        super().__init__(level=int(level), shuffle=shuffle, delta=delta)
        self._level = int(level)
        self._init_shuffle(shuffle)

    def make_codec(self) -> Codec:
        return Zstd(level=self._level)


@register
class LZMAAdapter(_ShuffleMixin):
    """LZMA / 7-Zip. Very high CR, very slow — Buccino et al. call this out."""

    name: ClassVar[str] = "lzma"
    lossy: ClassVar[bool] = False

    def __init__(self, preset: int | str = 6, shuffle: str = "no", delta: str = "no") -> None:
        super().__init__(preset=int(preset), shuffle=shuffle, delta=delta)
        self._preset = int(preset)
        self._init_shuffle(shuffle)

    def make_codec(self) -> Codec:
        return LZMA(preset=self._preset)
