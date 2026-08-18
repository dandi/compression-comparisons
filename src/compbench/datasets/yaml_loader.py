"""Loader indirection through a YAML config file.

Config schema::

    loader: synthetic                # scheme
    params:                          # forwarded to the loader
        duration_s: 5.0
        sample_rate_hz: 1000
        n_channels: 4
        seed: 42
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from compbench.datasets import register
from compbench.datasets.base import LoadedDataset


@register("yaml")
def load_yaml(path: str | Path, **overrides: Any) -> LoadedDataset:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"YAML dataset config not found: {p}")
    with p.open() as f:
        cfg = yaml.safe_load(f) or {}
    scheme = cfg.get("loader")
    if not scheme:
        raise ValueError(f"YAML {p} missing required `loader:` key")
    params = dict(cfg.get("params", {}))
    params.update(overrides)
    # Late import to avoid a cycle.
    from compbench.datasets import load as _load

    ds = _load(f"{scheme}:", **params)
    ds.provenance.setdefault("yaml_source", str(p))
    return ds
