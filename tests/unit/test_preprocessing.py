"""Unit tests for compbench.preprocessing + YAML-driven wiring."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import yaml

from compbench import datasets, preprocessing


@pytest.mark.ai_generated
def test_registered_kinds() -> None:
    assert "bandpass" in preprocessing.registered()


@pytest.mark.ai_generated
def test_apply_noop_when_no_steps() -> None:
    data = np.arange(20, dtype=np.int16).reshape(10, 2)
    out = preprocessing.apply(data, sample_rate_hz=1000.0, steps=None)
    assert out is data


@pytest.mark.ai_generated
def test_apply_unknown_kind_raises() -> None:
    with pytest.raises(ValueError, match="unknown kind"):
        preprocessing.apply(np.zeros(10), 1000.0, [{"kind": "no-such"}])


@pytest.mark.ai_generated
def test_bandpass_preserves_shape_and_dtype() -> None:
    pytest.importorskip("scipy")
    rng = np.random.default_rng(0)
    data = rng.integers(-1000, 1000, size=(4000, 3), dtype=np.int16)
    out = preprocessing.apply(
        data, 30_000.0, [{"kind": "bandpass", "low_hz": 300, "high_hz": 6000}]
    )
    assert out.shape == data.shape
    assert out.dtype == data.dtype
    assert out.flags["C_CONTIGUOUS"]


@pytest.mark.ai_generated
def test_bandpass_attenuates_low_frequency() -> None:
    """A 10 Hz sinusoid should be strongly attenuated by a 300-6000 Hz filter."""
    pytest.importorskip("scipy")
    fs = 30_000.0
    n = 30_000  # 1 s
    t = np.arange(n) / fs
    lo = (1000 * np.sin(2 * np.pi * 10 * t)).astype(np.int16).reshape(-1, 1)
    out = preprocessing.apply(lo, fs, [{"kind": "bandpass", "low_hz": 300, "high_hz": 6000}])
    # Steady-state amplitude should be ~0.
    steady = out[500:-500]  # avoid filtfilt edge transients
    assert np.abs(steady).max() < 100, f"low-freq not attenuated: max={np.abs(steady).max()}"


@pytest.mark.ai_generated
def test_bandpass_passes_in_band() -> None:
    """A 1 kHz sinusoid should pass largely intact through 300-6000 Hz."""
    pytest.importorskip("scipy")
    fs = 30_000.0
    n = 30_000
    t = np.arange(n) / fs
    amp = 1000.0
    signal = (amp * np.sin(2 * np.pi * 1000 * t)).astype(np.int16).reshape(-1, 1)
    out = preprocessing.apply(signal, fs, [{"kind": "bandpass", "low_hz": 300, "high_hz": 6000}])
    steady = out[500:-500]
    assert np.abs(steady).max() > 800  # peak preserved (~amp)


@pytest.mark.ai_generated
def test_bandpass_rejects_invalid_freqs() -> None:
    pytest.importorskip("scipy")
    with pytest.raises(ValueError, match="0 < low"):
        preprocessing.apply(
            np.zeros(1000, dtype=np.int16).reshape(-1, 1),
            1000.0,
            [{"kind": "bandpass", "low_hz": 300, "high_hz": 6000}],
        )  # high 6000 > Nyquist 500


@pytest.mark.ai_generated
def test_yaml_loader_applies_preprocessing(tmp_path: Path) -> None:
    """YAML with preprocessing: block runs the filter through the loader."""
    pytest.importorskip("scipy")
    cfg = {
        "loader": "synthetic",
        "params": {
            "duration_s": 1.0,
            "sample_rate_hz": 30_000,
            "n_channels": 2,
            "seed": 3,
        },
        "preprocessing": [{"kind": "bandpass", "low_hz": 300, "high_hz": 6000}],
    }
    p = tmp_path / "ds.yaml"
    p.write_text(yaml.safe_dump(cfg))
    ds = datasets.load(str(p))
    assert ds.data.shape == (30_000, 2)
    assert ds.data.dtype == np.int16
    assert ds.data.flags["C_CONTIGUOUS"]
    assert ds.provenance["preprocessing"] == [{"kind": "bandpass", "low_hz": 300, "high_hz": 6000}]


@pytest.mark.ai_generated
def test_yaml_loader_no_preprocessing_key_untouched(tmp_path: Path) -> None:
    """Without a `preprocessing:` block, loader is a straight pass-through."""
    p = tmp_path / "ds.yaml"
    p.write_text(yaml.safe_dump({"loader": "synthetic", "params": {"duration_s": 0.05, "seed": 1}}))
    ds = datasets.load(str(p))
    assert "preprocessing" not in ds.provenance
