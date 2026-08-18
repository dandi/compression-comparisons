"""Regression: `compbench run` must exit 2 when a `lossy=False` codec fails
round-trip byte-equality. Registers a fake, deliberately-lying codec and
invokes the CLI in-process via Click's runner.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import pytest
from click.testing import CliRunner
from numcodecs.abc import Codec

from compbench import codecs
from compbench.cli import main
from compbench.codecs.base import CodecAdapter


class _ZeroingCodec(Codec):  # type: ignore[misc]  # numcodecs.abc.Codec is untyped
    """Fake codec: encode returns an empty payload, decode returns all-zeros
    of the caller's expected byte count. Byte-equality with any nonzero input
    fails — exactly the case `--fail-on-lossless-mismatch` must catch.
    """

    codec_id = "compbench-lie"

    def __init__(self, expected_nbytes: int = 0) -> None:
        self.expected_nbytes = int(expected_nbytes)

    def get_config(self) -> dict[str, Any]:
        return {"id": self.codec_id, "expected_nbytes": self.expected_nbytes}

    def encode(self, buf: Any) -> bytes:
        arr = np.asarray(buf)
        # Prefix the payload with the input's total byte-count so decode can
        # reconstruct a matching-shape all-zero output.
        return arr.nbytes.to_bytes(8, "little")

    def decode(self, buf: Any, out: np.ndarray | None = None) -> np.ndarray:
        nbytes = int.from_bytes(bytes(buf)[:8], "little")
        return np.zeros(nbytes, dtype=np.uint8)


class _LyingAdapter(CodecAdapter):
    """Claims lossless but always drops data — used only under a fixture."""

    name: ClassVar[str] = "compbench-lie"
    lossy: ClassVar[bool] = False

    def make_codec(self) -> Codec:
        return _ZeroingCodec()


@pytest.fixture
def _lying_codec_registered() -> None:
    # Insert directly into the registry (bypassing `register()`'s duplicate
    # check so tests can be re-run without hitting a stale registration).
    codecs._REGISTRY[_LyingAdapter.name] = _LyingAdapter
    try:
        yield
    finally:
        codecs._REGISTRY.pop(_LyingAdapter.name, None)


@pytest.mark.ai_generated
def test_run_exits_2_when_lossless_codec_lies(
    tmp_path: Path, _lying_codec_registered: None
) -> None:
    out = tmp_path / "cell"
    r = CliRunner().invoke(
        main,
        [
            "run",
            "--input",
            "synthetic:duration_s=0.05,sample_rate_hz=1000,n_channels=2,seed=1",
            "--codec",
            "compbench-lie",
            "--output-dir",
            str(out),
        ],
    )
    assert r.exit_code == 2, (
        f"expected exit=2 (lossless-mismatch guard); got {r.exit_code}\n{r.output}"
    )
    assert "lossless codec produced non-exact round-trip" in r.output
    # Guard fires *after* writing artifacts — metrics.json must record the truth.
    metrics = json.loads((out / "metrics.json").read_text())
    assert metrics["expected_lossless"] is True
    assert metrics["round_trip_ok"] is False


@pytest.mark.ai_generated
def test_run_allows_lossy_mismatch_when_flag_disabled(
    tmp_path: Path, _lying_codec_registered: None
) -> None:
    r = CliRunner().invoke(
        main,
        [
            "run",
            "--input",
            "synthetic:duration_s=0.05,sample_rate_hz=1000,n_channels=2,seed=1",
            "--codec",
            "compbench-lie",
            "--output-dir",
            str(tmp_path / "cell"),
            "--no-fail-on-lossless-mismatch",
        ],
    )
    assert r.exit_code == 0
