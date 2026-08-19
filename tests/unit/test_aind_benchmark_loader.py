"""Unit tests for the AIND ephys-compression benchmark loader.

We synthesise a minimal binary-folder layout on tmp and assert the loader
constructs a working Recording and returns the requested slice.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("spikeinterface")

from compbench import datasets
from compbench.datasets import aind_benchmark as ab


def _make_fake_recording(tmp_path: Path, n_samples: int = 10_000, n_channels: int = 8) -> Path:
    """Emit a minimal AIND `binary_folder` layout — binary.json + raw file."""
    folder = tmp_path / "fake-rec"
    folder.mkdir()
    data = np.arange(n_samples * n_channels, dtype=np.int16).reshape(n_samples, n_channels)
    (folder / "traces_cached_seg0.raw").write_bytes(data.tobytes())
    (folder / "binary.json").write_text(
        json.dumps(
            {
                "class": "BinaryRecordingExtractor",
                "kwargs": {
                    "file_paths": ["traces_cached_seg0.raw"],
                    "sampling_frequency": 30000.0,
                    "num_chan": n_channels,
                    "dtype": "<i2",
                },
            }
        )
    )
    return folder


@pytest.mark.ai_generated
def test_registered() -> None:
    assert "aind-benchmark" in datasets.schemes()


@pytest.mark.ai_generated
def test_load_full(tmp_path: Path) -> None:
    folder = _make_fake_recording(tmp_path, n_samples=5000, n_channels=4)
    ds = ab.load_aind_benchmark(folder)
    assert ds.data.shape == (5000, 4)
    assert ds.data.dtype == np.int16
    assert ds.sample_rate_hz == 30000.0
    assert ds.data.flags["C_CONTIGUOUS"]
    assert ds.provenance["loader"] == "aind-benchmark"
    assert ds.provenance["spikeinterface"]["folder_name"] == "fake-rec"


@pytest.mark.ai_generated
def test_load_slice(tmp_path: Path) -> None:
    folder = _make_fake_recording(tmp_path, n_samples=30000, n_channels=4)
    ds = ab.load_aind_benchmark(folder, start_s=0.1, duration_s=0.5)
    # 30 kHz * 0.5 s = 15000 samples
    assert ds.data.shape == (15000, 4)


@pytest.mark.ai_generated
def test_load_channel_subset(tmp_path: Path) -> None:
    folder = _make_fake_recording(tmp_path, n_samples=1000, n_channels=8)
    ds = ab.load_aind_benchmark(folder, channel_indices="0,2,4,6")
    assert ds.data.shape == (1000, 4)


@pytest.mark.ai_generated
def test_load_missing_folder(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        ab.load_aind_benchmark(tmp_path / "nonexistent")


@pytest.mark.ai_generated
def test_load_folder_without_binary_json(tmp_path: Path) -> None:
    folder = tmp_path / "bad"
    folder.mkdir()
    with pytest.raises(FileNotFoundError, match=r"binary\.json"):
        ab.load_aind_benchmark(folder)


@pytest.mark.ai_generated
def test_load_via_uri_scheme(tmp_path: Path) -> None:
    folder = _make_fake_recording(tmp_path, n_samples=3000, n_channels=2)
    ds = datasets.load(f"aind-benchmark:path={folder},duration_s=0.05")
    assert ds.data.shape == (1500, 2)
