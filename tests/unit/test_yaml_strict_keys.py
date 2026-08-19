"""Regression tests for unknown-key rejection in YAML + codec adapters.

Silent typo acceptance is a bug factory at 336-cell scale (reviewer R4-B3).
`preproccessing:` (double-c typo) used to be silently dropped; now it must
raise. Same for unknown adapter kwargs.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from compbench import codecs, datasets


@pytest.mark.ai_generated
def test_yaml_rejects_unknown_top_level_key(tmp_path: Path) -> None:
    p = tmp_path / "ds.yaml"
    p.write_text(
        yaml.safe_dump(
            {
                "loader": "synthetic",
                "params": {"duration_s": 0.05},
                "preproccessing": [{"kind": "bandpass"}],  # typo: extra 'c'
            }
        )
    )
    with pytest.raises(ValueError, match="unknown top-level key"):
        datasets.load(str(p))


@pytest.mark.ai_generated
def test_yaml_accepts_all_known_keys(tmp_path: Path) -> None:
    p = tmp_path / "ds.yaml"
    p.write_text(
        yaml.safe_dump(
            {
                "loader": "synthetic",
                "params": {"duration_s": 0.05, "sample_rate_hz": 30000, "n_channels": 2},
                "preprocessing": [{"kind": "bandpass", "low_hz": 300, "high_hz": 6000}],
            }
        )
    )
    ds = datasets.load(str(p))
    assert ds.data.shape == (1500, 2)


@pytest.mark.ai_generated
def test_blosc_zstd_rejects_unknown_kwarg() -> None:
    """Adapter no longer accepts **kw — typos loudly fail."""
    with pytest.raises(TypeError):
        codecs.get("blosc-zstd")(level=3, shufle="byte")  # typo: 'shufle'


@pytest.mark.ai_generated
def test_zstd_rejects_unknown_kwarg() -> None:
    with pytest.raises(TypeError):
        codecs.get("zstd")(level=3, unknown_param=42)


@pytest.mark.ai_generated
def test_t261_rejects_unknown_kwarg() -> None:
    from compbench.codecs.t261 import _AVAILABLE

    if not _AVAILABLE:
        pytest.skip("BWC binaries not found")
    with pytest.raises(TypeError):
        codecs.get("t261")(preset="combinedPresetEEG_IndepChannel_lossless", fizzbuzz=1)


@pytest.mark.ai_generated
def test_preprocessing_clip_raises_not_silent() -> None:
    """Filter output exceeding int16 range must raise, not silently clip."""
    from compbench import preprocessing

    pytest.importorskip("scipy")
    import numpy as np

    # Build a signal that will nearly saturate int16 (~32000) at 1 kHz sinusoid;
    # filtfilt of a full-scale in-band sine can transiently exceed the container
    # near the edges — we expect an error.
    fs = 30_000.0
    n = 30_000
    t = np.arange(n) / fs
    amp = 32000.0
    data = (amp * np.sin(2 * np.pi * 1000 * t)).astype(np.int16).reshape(-1, 1)
    # Force a clip by pushing amplitude past int16 range via filter transient +
    # a step at the edge.
    data[0] = 32767
    with pytest.raises(ValueError, match="would clip"):
        preprocessing.apply(data, fs, [{"kind": "bandpass", "low_hz": 300, "high_hz": 6000}])


@pytest.mark.ai_generated
def test_t261_describe_includes_bwc_provenance() -> None:
    """R2-H6: manifest must carry BWC git SHA + version + resolved paths."""
    from compbench.codecs.t261 import _AVAILABLE

    if not _AVAILABLE:
        pytest.skip("BWC binaries not found")
    adapter = codecs.get("t261")()
    desc = adapter.describe()
    assert "bwc" in desc
    assert desc["bwc"]["bwc_git_sha"] is not None
    assert len(desc["bwc"]["bwc_git_sha"]) == 40  # git SHA
    assert desc["bwc"]["encoder_version"] is not None
    assert "BWC" in desc["bwc"]["encoder_version"]  # e.g. "BWC-6.0-2-g34c2a2a"
    assert desc["bwc"]["encoder_path"] is not None
    assert desc["bwc"]["decoder_path"] is not None
