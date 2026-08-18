"""Blosc-family codec adapters (level 0 of Phase 0: `blosc-zstd` only)."""

from __future__ import annotations

from typing import Any, ClassVar

from numcodecs import Blosc
from numcodecs.abc import Codec

from compbench.codecs import register
from compbench.codecs.base import CodecAdapter

_SHUFFLE = {"none": Blosc.NOSHUFFLE, "byte": Blosc.SHUFFLE, "bit": Blosc.BITSHUFFLE}


@register
class BloscZstdAdapter(CodecAdapter):
    """`blosc` meta-compressor with the `zstd` inner codec."""

    name: ClassVar[str] = "blosc-zstd"
    lossy: ClassVar[bool] = False

    def __init__(self, level: int | str = 3, shuffle: str = "byte", **kw: Any) -> None:
        super().__init__(level=int(level), shuffle=shuffle, **kw)
        if shuffle not in _SHUFFLE:
            raise ValueError(f"shuffle must be one of {list(_SHUFFLE)}; got {shuffle!r}")
        self._level = int(level)
        self._shuffle = _SHUFFLE[shuffle]

    def make_codec(self) -> Codec:
        return Blosc(cname="zstd", clevel=self._level, shuffle=self._shuffle)
