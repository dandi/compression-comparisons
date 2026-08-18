"""Profile parsing + sweep-matrix expansion.

A profile YAML has:

    name: paper           # results directory suffix
    datasets:
      - configs/datasets/foo.yaml
      - synthetic:duration_s=5.0,seed=0
    codecs:
      - codec: blosc-zstd
        params: {level: 3, shuffle: byte}
      - codec: wavpack
        params: {level: 2}
      - codec: wavpack
        params: {level: 2, bps: 2.25}   # lossy

`expand_matrix()` yields one `Cell` per (dataset x codec-config) pair, with
a stable, filesystem-safe `cell_id` derived from those two — the Snakefile
uses this ID as the directory name under `results/<profile>/`.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Cell:
    """One (dataset x codec x params) combination in the sweep matrix."""

    cell_id: str
    dataset_spec: str  # what compbench --input consumes
    codec: str  # what compbench --codec consumes
    codec_params: dict[str, Any] = field(default_factory=dict)
    dataset_label: str = ""  # short human-readable name
    codec_label: str = ""  # short human-readable name

    @property
    def codec_params_cli(self) -> str:
        """Serialise params as ``k=v,k=v`` for `compbench --codec-params`."""
        return ",".join(f"{k}={v}" for k, v in self.codec_params.items())


@dataclass
class Profile:
    name: str
    datasets: list[str]
    codecs: list[dict[str, Any]]

    def raw(self) -> dict[str, Any]:
        return {"name": self.name, "datasets": self.datasets, "codecs": self.codecs}


def load_profile(path: str | Path) -> Profile:
    p = Path(path)
    with p.open() as f:
        raw = yaml.safe_load(f) or {}
    name = raw.get("name")
    if not name:
        raise ValueError(f"Profile {p}: missing `name:`")
    datasets = raw.get("datasets") or []
    if not isinstance(datasets, list) or not datasets:
        raise ValueError(f"Profile {p}: `datasets:` must be a non-empty list")
    codecs = raw.get("codecs") or []
    if not isinstance(codecs, list) or not codecs:
        raise ValueError(f"Profile {p}: `codecs:` must be a non-empty list")
    for i, c in enumerate(codecs):
        if not isinstance(c, dict) or "codec" not in c:
            raise ValueError(f"Profile {p}: codecs[{i}] must be a dict with `codec:`")
    return Profile(name=str(name), datasets=[str(d) for d in datasets], codecs=list(codecs))


_SAFE_CHAR = re.compile(r"[^a-zA-Z0-9._-]")


def _slug(value: str, maxlen: int = 40) -> str:
    """Filesystem-safe slug — replaces unsafe chars, truncates."""
    s = _SAFE_CHAR.sub("_", value)
    return s[:maxlen].strip("_") or "x"


def _dataset_label(spec: str) -> str:
    """Short label — filename stem for a path, scheme for a URI, else slug."""
    if ":" in spec and not Path(spec).exists():
        scheme = spec.split(":", 1)[0]
        return _slug(scheme, 20)
    return _slug(Path(spec).stem, 30)


def _codec_label(codec: str, params: dict[str, Any]) -> str:
    """Short label — codec-name + hyphen-joined k=v pairs, hashed if too long."""
    if not params:
        return _slug(codec, 30)
    kv = "-".join(f"{k}={v}" for k, v in params.items())
    combined = f"{codec}-{kv}"
    if len(combined) <= 60:
        return _slug(combined, 60)
    # Too long — keep the codec name and hash the params for uniqueness.
    h = hashlib.sha256(kv.encode()).hexdigest()[:8]
    return _slug(f"{codec}-{h}", 30)


def _cell_id(dataset_label: str, codec_label: str) -> str:
    return f"{dataset_label}__{codec_label}"


def expand_matrix(profile: Profile) -> Iterator[Cell]:
    """Yield every (dataset x codec-config) cell in the profile."""
    seen: set[str] = set()
    for dspec in profile.datasets:
        dlabel = _dataset_label(dspec)
        for cfg in profile.codecs:
            codec_name = str(cfg["codec"])
            params = dict(cfg.get("params", {}))
            clabel = _codec_label(codec_name, params)
            cid = _cell_id(dlabel, clabel)
            if cid in seen:
                # Collision → hash-suffix to disambiguate.
                extra = hashlib.sha256(f"{dspec}|{codec_name}|{params}".encode()).hexdigest()[:6]
                cid = f"{cid}_{extra}"
            seen.add(cid)
            yield Cell(
                cell_id=cid,
                dataset_spec=dspec,
                codec=codec_name,
                codec_params=params,
                dataset_label=dlabel,
                codec_label=clabel,
            )
