"""Dataset loader registry.

A dataset loader takes an input spec (path, YAML config, or URI-like string)
and returns a `LoadedDataset` — the raw numpy array plus metadata the
benchmark needs (sample rate, channel count, provenance).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from compbench.datasets.base import LoadedDataset

_LOADERS: dict[str, Callable[..., LoadedDataset]] = {}


def register(scheme: str) -> Callable[[Callable[..., LoadedDataset]], Callable[..., LoadedDataset]]:
    """Decorator: register a loader under a URI-scheme-like name (e.g. `synthetic`)."""

    def _wrap(fn: Callable[..., LoadedDataset]) -> Callable[..., LoadedDataset]:
        if scheme in _LOADERS:
            raise ValueError(f"Loader scheme {scheme!r} already registered.")
        _LOADERS[scheme] = fn
        return fn

    return _wrap


def schemes() -> list[str]:
    """Registered scheme names."""
    return sorted(_LOADERS)


def load(spec: str | Path, **kwargs: Any) -> LoadedDataset:
    """Load a dataset from a spec.

    Supported spec forms:
    - ``synthetic:seed=0,duration_s=10,...`` — parameters routed to the synthetic loader
    - path to a ``.npy`` file — loaded as raw int16 with metadata inferred from filename
    - path to a ``.yaml`` file — parsed for a ``loader:`` key + ``params:`` block

    Any ``kwargs`` are merged into the loader's parameters (kwargs win over spec).
    """
    spec_str = str(spec)
    if ":" in spec_str and not Path(spec_str).exists():
        scheme, _, param_str = spec_str.partition(":")
        params = _parse_kv(param_str) if param_str else {}
        params.update(kwargs)
        try:
            fn = _LOADERS[scheme]
        except KeyError:
            available = ", ".join(sorted(_LOADERS)) or "<none>"
            raise KeyError(f"Unknown loader scheme {scheme!r}. Registered: {available}") from None
        return fn(**params)

    path = Path(spec_str)
    if path.suffix == ".npy":
        return _LOADERS["npy"](path=path, **kwargs)
    if path.suffix in {".yaml", ".yml"}:
        return _LOADERS["yaml"](path=path, **kwargs)
    raise ValueError(f"Cannot infer loader for spec {spec_str!r}")


def _parse_kv(s: str) -> dict[str, Any]:
    """Parse ``k1=v1,k2=v2`` — values kept as strings; loaders coerce."""
    out: dict[str, Any] = {}
    for chunk in s.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" not in chunk:
            raise ValueError(f"Expected k=v pair, got {chunk!r}")
        k, _, v = chunk.partition("=")
        out[k.strip()] = v.strip()
    return out


# Import side-effect: register loaders.
import contextlib as _contextlib  # noqa: E402

from compbench.datasets import npy as _npy  # noqa: F401,E402
from compbench.datasets import synthetic as _synthetic  # noqa: F401,E402
from compbench.datasets import yaml_loader as _yaml  # noqa: F401,E402

# Optional loaders — require extra packages.
with _contextlib.suppress(ImportError):
    from compbench.datasets import spikeinterface_loader as _si  # noqa: F401

__all__ = ["LoadedDataset", "load", "register", "schemes"]
