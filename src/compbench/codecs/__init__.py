"""Codec registry.

Codec adapters wrap `numcodecs.abc.Codec` with metadata that the benchmark
needs (parameter schema, lossless-vs-lossy flag, human description). Adapters
register themselves at import time via `register`.
"""

from __future__ import annotations

from collections.abc import Iterable

from compbench.codecs.base import CodecAdapter

_REGISTRY: dict[str, type[CodecAdapter]] = {}


def register(cls: type[CodecAdapter]) -> type[CodecAdapter]:
    """Decorator: register a codec adapter class by its `.name`."""
    if not cls.name:
        raise ValueError(f"Codec adapter {cls!r} must set a non-empty `name`.")
    if cls.name in _REGISTRY:
        raise ValueError(f"Codec {cls.name!r} already registered.")
    _REGISTRY[cls.name] = cls
    return cls


def get(name: str) -> type[CodecAdapter]:
    """Look up a registered codec adapter class."""
    try:
        return _REGISTRY[name]
    except KeyError:
        available = ", ".join(sorted(_REGISTRY)) or "<none>"
        raise KeyError(f"Unknown codec {name!r}. Registered: {available}") from None


def names() -> list[str]:
    """Sorted list of registered codec names."""
    return sorted(_REGISTRY)


def all_adapters() -> Iterable[type[CodecAdapter]]:
    """Iterate over all registered adapter classes."""
    return _REGISTRY.values()


# Import side-effect: register the built-in codecs.
# Optional codecs — audio (FLAC, WavPack) require extra packages that may not
# be available on every platform (e.g. wavpack-numcodecs ships glibc-specific
# binaries). If the import fails, those codecs simply aren't registered.
import contextlib as _contextlib  # noqa: E402

from compbench.codecs import blosc as _blosc  # noqa: F401,E402
from compbench.codecs import standard as _standard  # noqa: F401,E402

with _contextlib.suppress(ImportError):
    from compbench.codecs import audio as _audio  # noqa: F401

from compbench.codecs import bittrunc  # noqa: E402,F401

# T.261 / H.BWC via subprocess — only registers if BWC binaries are findable.
from compbench.codecs import t261 as _t261  # noqa: F401,E402

__all__ = ["CodecAdapter", "all_adapters", "get", "names", "register"]
