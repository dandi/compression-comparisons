"""Single-library codec adapters — thin wrappers around `numcodecs` classes
for the general-purpose compressors evaluated in Buccino et al. Fig 2.
"""

from __future__ import annotations

from typing import Any, ClassVar

from numcodecs import LZ4, LZMA, GZip, Zlib, Zstd
from numcodecs.abc import Codec

from compbench.codecs import register
from compbench.codecs.base import CodecAdapter


@register
class GZipAdapter(CodecAdapter):
    """Gzip framing over deflate (Python `zlib` + gzip header)."""

    name: ClassVar[str] = "gzip"
    lossy: ClassVar[bool] = False

    def __init__(self, level: int | str = 5, **kw: Any) -> None:
        super().__init__(level=int(level), **kw)
        self._level = int(level)

    def make_codec(self) -> Codec:
        return GZip(level=self._level)


@register
class ZlibAdapter(CodecAdapter):
    """Raw deflate (no gzip framing)."""

    name: ClassVar[str] = "zlib"
    lossy: ClassVar[bool] = False

    def __init__(self, level: int | str = 5, **kw: Any) -> None:
        super().__init__(level=int(level), **kw)
        self._level = int(level)

    def make_codec(self) -> Codec:
        return Zlib(level=self._level)


@register
class LZ4Adapter(CodecAdapter):
    """Raw LZ4 (no blosc framing)."""

    name: ClassVar[str] = "lz4"
    lossy: ClassVar[bool] = False

    def __init__(self, acceleration: int | str = 1, **kw: Any) -> None:
        super().__init__(acceleration=int(acceleration), **kw)
        self._acceleration = int(acceleration)

    def make_codec(self) -> Codec:
        return LZ4(acceleration=self._acceleration)


@register
class ZstdAdapter(CodecAdapter):
    """Raw Zstandard (no blosc framing)."""

    name: ClassVar[str] = "zstd"
    lossy: ClassVar[bool] = False

    def __init__(self, level: int | str = 3, **kw: Any) -> None:
        super().__init__(level=int(level), **kw)
        self._level = int(level)

    def make_codec(self) -> Codec:
        return Zstd(level=self._level)


@register
class LZMAAdapter(CodecAdapter):
    """LZMA / 7-Zip. Very high CR, very slow — Buccino et al. call this out."""

    name: ClassVar[str] = "lzma"
    lossy: ClassVar[bool] = False

    def __init__(self, preset: int | str = 6, **kw: Any) -> None:
        super().__init__(preset=int(preset), **kw)
        self._preset = int(preset)

    def make_codec(self) -> Codec:
        return LZMA(preset=self._preset)
