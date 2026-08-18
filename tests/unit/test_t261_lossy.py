"""Unit tests for T.261 lossy controls (StepSizeForQP, MaxAbsDeltaQP)."""

from __future__ import annotations

import numpy as np
import pytest

from compbench.codecs import t261 as t261_mod

pytestmark = pytest.mark.skipif(not t261_mod._AVAILABLE, reason="BWC binaries not found")


@pytest.mark.ai_generated
def test_lossy_flag_flips_when_qp_gt_one() -> None:
    from compbench import codecs

    adapter = codecs.get("t261")(
        preset="combinedPresetEEG_IndepChannel_lossless",
        step_size_for_qp=2.0,
    )
    # QP override wins even if preset name says lossless.
    assert adapter.lossy is True


@pytest.mark.ai_generated
def test_lossy_flag_stays_false_at_qp_one() -> None:
    from compbench import codecs

    adapter = codecs.get("t261")(
        preset="combinedPresetEEG_IndepChannel_lossless",
        step_size_for_qp=1.0,
    )
    assert adapter.lossy is False


@pytest.mark.ai_generated
def test_qp_override_appears_in_cli() -> None:
    codec = t261_mod.T261Codec(
        preset="combinedPresetEEG_IndepChannel_lossless",
        step_size_for_qp=2.5,
        max_abs_delta_qp=4,
    )
    args = codec._build_overrides()
    assert "--StepSizeForQP=2.5" in args
    assert "--MaxAbsDeltaQP=4" in args


@pytest.mark.ai_generated
def test_no_qp_override_when_unset() -> None:
    codec = t261_mod.T261Codec(preset="combinedPresetEEG_IndepChannel_lossless")
    args = codec._build_overrides()
    assert not any(a.startswith("--StepSizeForQP=") for a in args)
    assert not any(a.startswith("--MaxAbsDeltaQP=") for a in args)


@pytest.mark.ai_generated
def test_extra_args_appended_after_qp() -> None:
    codec = t261_mod.T261Codec(
        preset="combinedPresetEEG_IndepChannel_lossless",
        step_size_for_qp=2.0,
        extra_args=("--Foo=bar",),
    )
    args = codec._build_overrides()
    # QP override before user extras, but both present.
    assert args.index("--StepSizeForQP=2.0") < args.index("--Foo=bar")


@pytest.mark.ai_generated
def test_get_config_roundtrip_includes_qp() -> None:
    codec = t261_mod.T261Codec(
        preset="combinedPresetEEG_IndepChannel_lossless",
        step_size_for_qp=3.0,
        max_abs_delta_qp=2,
    )
    cfg = codec.get_config()
    assert cfg["step_size_for_qp"] == 3.0
    assert cfg["max_abs_delta_qp"] == 2


@pytest.mark.ai_generated
def test_lossy_encode_produces_smaller_output_and_lossless_larger_or_equal() -> None:
    """A higher QP step should yield stronger compression than lossless
    on a real signal — the sanity check that lossy is actually lossy."""
    rng = np.random.default_rng(0)
    t = np.arange(4000, dtype=np.float64) / 1000.0
    signal = 1000.0 * np.sin(2 * np.pi * 5 * t)
    data = np.column_stack(
        [signal + 50 * ch + 30 * rng.standard_normal(4000) for ch in range(4)]
    ).astype(np.int16)

    lossless = t261_mod.T261Codec(preset="combinedPresetEEG_IndepChannel_lossless")
    lossy = t261_mod.T261Codec(
        preset="combinedPresetEEG_IndepChannel_lossless",
        step_size_for_qp=5.0,
    )
    b_lossless = lossless.encode(data)
    b_lossy = lossy.encode(data)
    assert len(b_lossy) < len(b_lossless), (
        f"lossy ({len(b_lossy)} B) should be smaller than lossless ({len(b_lossless)} B)"
    )

    # And decoded lossy output must differ from original by more than 0 but stay finite.
    dec_lossy = lossy.decode(b_lossy)
    assert dec_lossy.shape == data.shape
    diff = np.abs(data.astype(np.int32) - dec_lossy.astype(np.int32)).max()
    assert diff > 0  # actually lossy
    assert diff < 32768  # sane bounds


@pytest.mark.ai_generated
def test_stock_lossy_preset_registers_as_lossy() -> None:
    from compbench import codecs

    adapter = codecs.get("t261")(preset="combinedPresetEEG_IndepChannel")
    assert adapter.lossy is True
