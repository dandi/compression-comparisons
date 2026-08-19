"""Loader indirection through a YAML config file.

Config schema::

    loader: synthetic                # scheme (routes to a registered loader)
    params:                          # forwarded to the loader
        duration_s: 5.0
        sample_rate_hz: 1000
        n_channels: 4
        seed: 42
    preprocessing:                   # optional, applied after load
        - kind: bandpass
          low_hz: 300
          high_hz: 6000
          order: 4
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from compbench import preprocessing as _pre
from compbench.datasets import register
from compbench.datasets.base import LoadedDataset


@register("yaml")
def load_yaml(path: str | Path, **overrides: Any) -> LoadedDataset:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"YAML dataset config not found: {p}")
    with p.open() as f:
        cfg = yaml.safe_load(f) or {}
    # Reject unknown top-level keys — silent typos ("preproccessing:" instead
    # of "preprocessing:") would otherwise ship as legitimate cells with the
    # wrong data and be very hard to debug at 336-cell scale.
    _allowed_keys = {"loader", "params", "preprocessing"}
    unknown = set(cfg) - _allowed_keys
    if unknown:
        raise ValueError(
            f"YAML {p}: unknown top-level key(s) {sorted(unknown)}. "
            f"Allowed: {sorted(_allowed_keys)}. "
            f"If you meant one of these, check for typos."
        )
    scheme = cfg.get("loader")
    if not scheme:
        raise ValueError(f"YAML {p} missing required `loader:` key")
    params = dict(cfg.get("params", {}))
    params.update(overrides)
    # Late import to avoid a cycle.
    from compbench.datasets import load as _load

    ds = _load(f"{scheme}:", **params)
    ds.provenance.setdefault("yaml_source", str(p))

    steps = cfg.get("preprocessing")
    if steps:
        ds.data = _pre.apply(ds.data, ds.sample_rate_hz, steps)
        # Re-enforce C-contiguity invariant after any preprocessor.
        import numpy as np

        if not ds.data.flags["C_CONTIGUOUS"]:
            ds.data = np.ascontiguousarray(ds.data)
        ds.provenance["preprocessing"] = list(steps)
    return ds
