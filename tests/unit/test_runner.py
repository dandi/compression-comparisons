"""Unit tests for compbench.runner."""

from __future__ import annotations

import pytest

from compbench.runner import run_cell


@pytest.mark.ai_generated
def test_run_cell_synthetic_blosc_zstd() -> None:
    result = run_cell(
        spec="synthetic:duration_s=0.5,sample_rate_hz=1000,n_channels=4,seed=0",
        codec_name="blosc-zstd",
        codec_params={"level": 3, "shuffle": "byte"},
    )
    assert result.metrics["round_trip_ok"] is True
    assert result.metrics["rmse"] == 0.0
    assert result.metrics["cr"] >= 1.0  # any compression at all
    assert result.metrics["encoded_bytes"] > 0
    assert result.metrics["original_bytes"] == 500 * 4 * 2  # int16
    assert result.metrics["encode_xrt"] is not None
    assert result.metrics["decode_xrt"] is not None
    assert result.metrics["expected_lossless"] is True
    assert result.manifest["input"]["n_channels"] == 4
    assert result.manifest["codec"]["name"] == "blosc-zstd"


@pytest.mark.ai_generated
def test_run_cell_keeps_reconstructed_when_asked() -> None:
    result = run_cell(
        spec="synthetic:duration_s=0.05",
        codec_name="blosc-zstd",
        keep_reconstructed=True,
    )
    assert result.reconstructed is not None
    assert result.encoded is not None


@pytest.mark.ai_generated
def test_run_cell_unknown_codec() -> None:
    with pytest.raises(KeyError):
        run_cell(spec="synthetic:duration_s=0.05", codec_name="no-such")
