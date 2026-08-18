"""Unit tests for the T.261 / H.BWC subprocess-based codec adapter.

Skipped module-wide if the BWC binaries were not found at import time (e.g.
if src/bwc/ was never built and BWC_BIN_DIR is unset).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from compbench.codecs import t261 as t261_mod

pytestmark = pytest.mark.skipif(not t261_mod._AVAILABLE, reason="BWC binaries not found")


@pytest.mark.ai_generated
def test_registered_only_when_available() -> None:
    from compbench import codecs

    assert "t261" in codecs.names()


@pytest.mark.ai_generated
def test_default_lossless() -> None:
    from compbench import codecs

    adapter = codecs.get("t261")()
    assert adapter.lossy is False


@pytest.mark.ai_generated
def test_lossy_when_preset_lacks_lossless_suffix() -> None:
    from compbench import codecs

    adapter = codecs.get("t261")(preset="combinedPresetEEG_IndepChannel")
    assert adapter.lossy is True


@pytest.mark.ai_generated
def test_unknown_preset_errors() -> None:
    with pytest.raises(ValueError, match="not found"):
        t261_mod.T261Codec(preset="no-such-preset-xyz")


@pytest.mark.ai_generated
def test_lossless_round_trip_int16() -> None:
    codec = t261_mod.T261Codec(preset="combinedPresetEEG_IndepChannel_lossless")
    rng = np.random.default_rng(0)
    # Structured (slowly-varying) data — T.261 compresses this well.
    t = np.arange(2000, dtype=np.float64) / 1000.0
    signal = 1000.0 * np.sin(2 * np.pi * 5 * t)
    data = np.column_stack(
        [signal + 50 * ch + 20 * rng.standard_normal(2000) for ch in range(4)]
    ).astype(np.int16)
    encoded = codec.encode(data)
    assert isinstance(encoded, bytes)
    assert len(encoded) < data.nbytes  # should compress
    decoded = codec.decode(encoded)
    assert decoded.shape == data.shape
    assert decoded.dtype == np.int16
    assert np.array_equal(data, decoded)


@pytest.mark.ai_generated
def test_bad_input_dtype_raises() -> None:
    codec = t261_mod.T261Codec()
    with pytest.raises(ValueError, match="int16"):
        codec.encode(np.zeros((100, 4), dtype=np.int32))


@pytest.mark.ai_generated
def test_bad_input_shape_raises() -> None:
    codec = t261_mod.T261Codec()
    with pytest.raises(ValueError, match="2D"):
        codec.encode(np.zeros(100, dtype=np.int16))


@pytest.mark.ai_generated
def test_rawh2_header_roundtrip(tmp_path: Path) -> None:
    data = np.arange(24, dtype=np.int16).reshape(6, 4)
    p = tmp_path / "x.raw"
    t261_mod._write_rawh2(p, data)
    back = t261_mod._read_rawh2(p)
    assert back.shape == data.shape
    assert np.array_equal(back, data)


@pytest.mark.ai_generated
def test_get_config_roundtrip() -> None:
    codec = t261_mod.T261Codec(preset="combinedPresetEEG_IndepChannel_lossless", bit_depth=16)
    cfg = codec.get_config()
    assert cfg["id"] == "t261"
    assert cfg["preset"] == "combinedPresetEEG_IndepChannel_lossless"
    assert cfg["bit_depth"] == 16


@pytest.mark.ai_generated
def test_runner_end_to_end_via_compbench() -> None:
    """Run one T.261 cell through the full runner (encode+decode+eval)."""
    from compbench.runner import run_cell

    result = run_cell(
        spec="synthetic:duration_s=0.5,sample_rate_hz=1000,n_channels=4,seed=0",
        codec_name="t261",
    )
    assert result.metrics["round_trip_ok"] is True
    assert result.metrics["rmse"] == 0.0
    assert result.metrics["cr"] > 1.0
    assert result.manifest["codec"]["name"] == "t261"
