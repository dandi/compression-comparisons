"""Blosc-family codec adapters — one class per (cname) so registry keys match
the paper's terminology (`blosc-lz4`, `blosc-lz4hc`, `blosc-zlib`, `blosc-zstd`).
"""

from __future__ import annotations

from typing import ClassVar

from numcodecs import Blosc
from numcodecs.abc import Codec

from compbench.codecs import register
from compbench.codecs.base import CodecAdapter

_SHUFFLE = {"none": Blosc.NOSHUFFLE, "byte": Blosc.SHUFFLE, "bit": Blosc.BITSHUFFLE}


class _BloscAdapter(CodecAdapter):
    """Shared implementation — subclasses set `name` and `_cname`."""

    _cname: ClassVar[str] = ""

    def __init__(self, level: int | str = 3, shuffle: str = "byte") -> None:
        super().__init__(level=int(level), shuffle=shuffle)
        if shuffle not in _SHUFFLE:
            raise ValueError(f"shuffle must be one of {list(_SHUFFLE)}; got {shuffle!r}")
        self._level = int(level)
        self._shuffle = _SHUFFLE[shuffle]

    def make_codec(self) -> Codec:
        return Blosc(cname=self._cname, clevel=self._level, shuffle=self._shuffle)


@register
class BloscZstdAdapter(_BloscAdapter):
    name: ClassVar[str] = "blosc-zstd"
    _cname: ClassVar[str] = "zstd"


@register
class BloscLz4Adapter(_BloscAdapter):
    name: ClassVar[str] = "blosc-lz4"
    _cname: ClassVar[str] = "lz4"


@register
class BloscLz4hcAdapter(_BloscAdapter):
    name: ClassVar[str] = "blosc-lz4hc"
    _cname: ClassVar[str] = "lz4hc"


@register
class BloscZlibAdapter(_BloscAdapter):
    name: ClassVar[str] = "blosc-zlib"
    _cname: ClassVar[str] = "zlib"
