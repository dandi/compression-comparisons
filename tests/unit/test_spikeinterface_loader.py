"""Unit tests for the SpikeInterface loader.

We use a real (in-memory) `NumpyRecording` from spikeinterface.core rather
than mocking — this exercises the actual `get_traces` API contract. If
spikeinterface is missing at test-collection time, the entire module is
skipped.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("spikeinterface")

from spikeinterface.core import NumpyRecording

from compbench import datasets
from compbench.datasets.spikeinterface_loader import (
    _detect_reader,
    _slice_recording,
)


@pytest.mark.ai_generated
def test_slice_recording_full() -> None:
    rng = np.random.default_rng(0)
    data = rng.integers(-100, 100, size=(1000, 4), dtype=np.int16)
    rec = NumpyRecording(traces_list=[data], sampling_frequency=1000.0)
    out = _slice_recording(rec, segment=0, start_s=0.0, duration_s=None)
    assert out.shape == (1000, 4)
    assert np.array_equal(out, data)
    assert out.flags["C_CONTIGUOUS"]


@pytest.mark.ai_generated
def test_slice_recording_slice() -> None:
    rng = np.random.default_rng(0)
    data = rng.integers(-100, 100, size=(1000, 4), dtype=np.int16)
    rec = NumpyRecording(traces_list=[data], sampling_frequency=1000.0)
    out = _slice_recording(rec, segment=0, start_s=0.2, duration_s=0.5)
    assert out.shape == (500, 4)
    assert np.array_equal(out, data[200:700])


@pytest.mark.ai_generated
def test_slice_recording_bad_segment() -> None:
    data = np.zeros((10, 2), dtype=np.int16)
    rec = NumpyRecording(traces_list=[data], sampling_frequency=1.0)
    with pytest.raises(ValueError):
        _slice_recording(rec, segment=5, start_s=0.0, duration_s=None)


@pytest.mark.ai_generated
def test_detect_reader_zarr(tmp_path: Path) -> None:
    d = tmp_path / "recording.zarr"
    d.mkdir()
    (d / ".zgroup").write_text("{}")
    assert _detect_reader(d) == "zarr"


@pytest.mark.ai_generated
def test_detect_reader_spikeglx(tmp_path: Path) -> None:
    d = tmp_path / "sglx"
    d.mkdir()
    (d / "run0_g0_t0.imec0.ap.bin").write_bytes(b"")
    (d / "run0_g0_t0.imec0.ap.meta").write_text("")
    assert _detect_reader(d) == "spikeglx"


@pytest.mark.ai_generated
def test_detect_reader_openephys(tmp_path: Path) -> None:
    d = tmp_path / "oe"
    (d / "sub").mkdir(parents=True)
    (d / "sub" / "structure.oebin").write_text("{}")
    assert _detect_reader(d) == "openephys"


@pytest.mark.ai_generated
def test_detect_reader_nwb(tmp_path: Path) -> None:
    p = tmp_path / "session.nwb"
    p.write_bytes(b"")
    assert _detect_reader(p) == "nwb_recording"


@pytest.mark.ai_generated
def test_detect_reader_unknown(tmp_path: Path) -> None:
    p = tmp_path / "mystery.dat"
    p.write_bytes(b"")
    with pytest.raises(ValueError):
        _detect_reader(p)


@pytest.mark.ai_generated
def test_loader_registered_in_scheme_registry() -> None:
    # Both aliases should be present.
    assert "spikeinterface" in datasets.schemes()
    assert "si" in datasets.schemes()
