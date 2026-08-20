"""Regression tests for round-2 R4-REG1: `lossless_violation` was inverted.

Before the fix:
- lossless codec + broken round-trip → violation=False (WRONG)
- lossy codec + broken round-trip → violation=True (WRONG)

After the fix:
- lossless codec + broken round-trip → violation=True (the alarm we want)
- everything else → violation=False
"""

from __future__ import annotations

from typing import Any, ClassVar

import numpy as np
import pytest
from numcodecs.abc import Codec

from compbench import codecs
from compbench.codecs.base import CodecAdapter
from compbench.runner import run_cell


class _ZeroingCodec(Codec):  # type: ignore[misc]  # numcodecs.abc.Codec is untyped
    codec_id = "compbench-lie2"

    def get_config(self) -> dict[str, Any]:
        return {"id": self.codec_id}

    def encode(self, buf: Any) -> bytes:
        arr = np.asarray(buf)
        return arr.nbytes.to_bytes(8, "little")

    def decode(self, buf: Any, out: np.ndarray | None = None) -> np.ndarray:
        nbytes = int.from_bytes(bytes(buf)[:8], "little")
        return np.zeros(nbytes, dtype=np.uint8)


class _LyingAdapter(CodecAdapter):
    name: ClassVar[str] = "compbench-lie2"
    lossy: ClassVar[bool] = False  # LIE

    def make_codec(self) -> Codec:
        return _ZeroingCodec()


class _TruthfulLossyAdapter(CodecAdapter):
    name: ClassVar[str] = "compbench-truthful-lossy"
    lossy: ClassVar[bool] = True  # honest

    def make_codec(self) -> Codec:
        return _ZeroingCodec()


@pytest.fixture
def _register_test_codecs() -> None:
    codecs._REGISTRY[_LyingAdapter.name] = _LyingAdapter
    codecs._REGISTRY[_TruthfulLossyAdapter.name] = _TruthfulLossyAdapter
    try:
        yield
    finally:
        codecs._REGISTRY.pop(_LyingAdapter.name, None)
        codecs._REGISTRY.pop(_TruthfulLossyAdapter.name, None)


@pytest.mark.ai_generated
def test_lossless_violation_true_when_declared_lossless_lies(
    _register_test_codecs: None,
) -> None:
    """Declared-lossless codec that returns garbage → violation=True."""
    result = run_cell(
        spec="synthetic:duration_s=0.05,n_channels=2",
        codec_name="compbench-lie2",
    )
    assert result.metrics["expected_lossless"] is True
    assert result.metrics["round_trip_ok"] is False
    assert result.metrics["lossless_violation"] is True  # THE alarm


@pytest.mark.ai_generated
def test_lossless_violation_false_when_lossy_codec_differs(
    _register_test_codecs: None,
) -> None:
    """Declared-lossy codec that differs from input is expected — not a violation."""
    result = run_cell(
        spec="synthetic:duration_s=0.05,n_channels=2",
        codec_name="compbench-truthful-lossy",
    )
    assert result.metrics["expected_lossless"] is False
    assert result.metrics["round_trip_ok"] is False
    assert result.metrics["lossless_violation"] is False


@pytest.mark.ai_generated
def test_lossless_violation_false_when_lossless_actually_lossless() -> None:
    """blosc-zstd is genuinely lossless and does round-trip → no violation."""
    result = run_cell(
        spec="synthetic:duration_s=0.05,n_channels=2",
        codec_name="blosc-zstd",
    )
    assert result.metrics["expected_lossless"] is True
    assert result.metrics["round_trip_ok"] is True
    assert result.metrics["lossless_violation"] is False
