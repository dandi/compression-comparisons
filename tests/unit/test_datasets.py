"""Unit tests for compbench.datasets."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import yaml

from compbench import datasets
from compbench.datasets.synthetic import load_synthetic


@pytest.mark.ai_generated
def test_synthetic_shape_and_dtype() -> None:
    ds = load_synthetic(duration_s=0.5, sample_rate_hz=1000, n_channels=3, seed=1)
    assert ds.data.shape == (500, 3)
    assert ds.data.dtype == np.int16
    assert ds.sample_rate_hz == 1000.0
    assert ds.duration_s == 0.5
    assert ds.n_channels == 3
    assert ds.provenance["loader"] == "synthetic"


@pytest.mark.ai_generated
def test_synthetic_determinism() -> None:
    a = load_synthetic(duration_s=0.1, seed=42)
    b = load_synthetic(duration_s=0.1, seed=42)
    c = load_synthetic(duration_s=0.1, seed=43)
    assert np.array_equal(a.data, b.data)
    assert not np.array_equal(a.data, c.data)


@pytest.mark.ai_generated
def test_synthetic_rejects_bad_args() -> None:
    with pytest.raises(ValueError):
        load_synthetic(duration_s=0)
    with pytest.raises(ValueError):
        load_synthetic(n_channels=0)


@pytest.mark.ai_generated
def test_load_via_uri_scheme() -> None:
    ds = datasets.load("synthetic:duration_s=0.2,sample_rate_hz=500,n_channels=2,seed=7")
    assert ds.data.shape == (100, 2)
    assert ds.sample_rate_hz == 500.0


@pytest.mark.ai_generated
def test_load_npy(tmp_path: Path) -> None:
    arr = np.arange(60, dtype=np.int16).reshape(20, 3)
    p = tmp_path / "sample.npy"
    np.save(p, arr)
    ds = datasets.load(str(p), sample_rate_hz=250.0)
    assert ds.data.shape == (20, 3)
    assert ds.sample_rate_hz == 250.0


@pytest.mark.ai_generated
def test_load_yaml(tmp_path: Path) -> None:
    cfg = {
        "loader": "synthetic",
        "params": {"duration_s": 0.05, "sample_rate_hz": 2000, "n_channels": 2, "seed": 3},
    }
    p = tmp_path / "ds.yaml"
    p.write_text(yaml.safe_dump(cfg))
    ds = datasets.load(str(p))
    assert ds.data.shape == (100, 2)
    assert ds.provenance["yaml_source"] == str(p)


@pytest.mark.ai_generated
def test_load_yaml_override(tmp_path: Path) -> None:
    p = tmp_path / "ds.yaml"
    p.write_text(yaml.safe_dump({"loader": "synthetic", "params": {"duration_s": 0.05, "seed": 3}}))
    ds = datasets.load(str(p), seed=99)
    ref = datasets.load("synthetic:duration_s=0.05,sample_rate_hz=1000,n_channels=4,seed=99")
    assert np.array_equal(ds.data, ref.data)


@pytest.mark.ai_generated
def test_load_unknown_scheme() -> None:
    with pytest.raises(KeyError):
        datasets.load("nonesuch:foo=bar")
