"""Blosc-family codec adapters — one class per (cname) so registry keys match
the paper's terminology (`blosc-lz4`, `blosc-lz4hc`, `blosc-zlib`, `blosc-zstd`).
"""

from __future__ import annotations

import os
from typing import ClassVar

import numcodecs.blosc as _blosc
from numcodecs import Blosc
from numcodecs.abc import Codec

from compbench.codecs import register
from compbench.codecs.base import CodecAdapter

_SHUFFLE = {"none": Blosc.NOSHUFFLE, "byte": Blosc.SHUFFLE, "bit": Blosc.BITSHUFFLE}


def _configure_threads() -> int:
    """Pin blosc's internal thread count; return what it was set to.

    Two reasons this is not left at the library default of 8.

    **Determinism.** Above one thread blosc is not reproducible: the same
    input yields a different compressed byte stream on every run. The
    *length* is stable — so compression ratio, our headline metric, is
    unaffected, and round-trip stays exact — but the artifact itself is
    not byte-reproducible, which is a strange property for a benchmark
    whose whole claim is that two runs agree.

    **Honest accounting.** The Snakemake rule declares ``threads: 1``, so
    ``--cores 21`` schedules 21 cells expecting 21 cores. With blosc
    defaulting to 8 that is ~168 threads on a 32-core box, and every
    wall-time and xRT number becomes a function of how many neighbours
    happened to be running. Parallelism belongs at the cell level.

    Override with ``COMPBENCH_BLOSC_THREADS`` (see ``.env``) — e.g. to
    reproduce a throughput measurement that deliberately uses in-codec
    threading.
    """
    n = int(os.environ.get("COMPBENCH_BLOSC_THREADS", "1"))
    if n > 0:
        _blosc.set_nthreads(n)
    return int(_blosc.get_nthreads())


BLOSC_NTHREADS = _configure_threads()


class _BloscAdapter(CodecAdapter):
    """Shared implementation — subclasses set `name` and `_cname`."""

    _cname: ClassVar[str] = ""

    def __init__(self, level: int | str = 3, shuffle: str = "byte", delta: str = "no") -> None:
        super().__init__(level=int(level), shuffle=shuffle, delta=delta)
        if shuffle not in _SHUFFLE:
            raise ValueError(f"shuffle must be one of {list(_SHUFFLE)}; got {shuffle!r}")
        self._level = int(level)
        self._shuffle = _SHUFFLE[shuffle]

    def make_codec(self) -> Codec:
        return Blosc(cname=self._cname, clevel=self._level, shuffle=self._shuffle)

    def describe(self) -> dict[str, object]:
        # Record the thread count: it does not change CR, but it does decide
        # whether the compressed bytes are reproducible (see _configure_threads).
        desc = super().describe()
        desc["blosc_nthreads"] = int(_blosc.get_nthreads())
        return desc


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
