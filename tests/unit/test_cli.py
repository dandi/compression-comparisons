"""Unit tests for the compbench CLI (via Click's testing runner — in-process)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from compbench.cli import main


@pytest.mark.ai_generated
def test_list_codecs_shows_blosc_zstd() -> None:
    runner = CliRunner()
    r = runner.invoke(main, ["list-codecs"])
    assert r.exit_code == 0, r.output
    assert "blosc-zstd" in r.output.splitlines()


@pytest.mark.ai_generated
def test_describe_codec_json() -> None:
    runner = CliRunner()
    r = runner.invoke(main, ["describe-codec", "blosc-zstd"])
    assert r.exit_code == 0, r.output
    d = json.loads(r.output)
    assert d["name"] == "blosc-zstd"
    assert d["lossy"] is False


@pytest.mark.ai_generated
def test_describe_codec_unknown() -> None:
    runner = CliRunner()
    r = runner.invoke(main, ["describe-codec", "no-such"])
    assert r.exit_code != 0
    assert "Unknown codec" in r.output


@pytest.mark.ai_generated
def test_run_writes_artifacts(tmp_path: Path) -> None:
    out = tmp_path / "cell"
    runner = CliRunner()
    r = runner.invoke(
        main,
        [
            "run",
            "--input",
            "synthetic:duration_s=0.2,sample_rate_hz=1000,n_channels=3,seed=1",
            "--codec",
            "blosc-zstd",
            "--codec-params",
            "level=5,shuffle=byte",
            "--output-dir",
            str(out),
        ],
    )
    assert r.exit_code == 0, r.output
    mf = json.loads((out / "manifest.json").read_text())
    mt = json.loads((out / "metrics.json").read_text())
    assert mf["input"]["n_channels"] == 3
    assert mf["codec"]["params"]["level"] == 5
    assert mt["round_trip_ok"] is True
    assert mt["rmse"] == 0.0
    assert mt["cr"] > 0


@pytest.mark.ai_generated
def test_run_bad_codec_params(tmp_path: Path) -> None:
    runner = CliRunner()
    r = runner.invoke(
        main,
        [
            "run",
            "--input",
            "synthetic:duration_s=0.05",
            "--codec",
            "blosc-zstd",
            "--codec-params",
            "not-a-kv",
            "--output-dir",
            str(tmp_path / "cell"),
        ],
    )
    assert r.exit_code != 0


@pytest.mark.ai_generated
def test_run_unknown_codec_errors(tmp_path: Path) -> None:
    runner = CliRunner()
    r = runner.invoke(
        main,
        [
            "run",
            "--input",
            "synthetic:duration_s=0.05",
            "--codec",
            "no-such",
            "--output-dir",
            str(tmp_path / "cell"),
        ],
    )
    assert r.exit_code != 0
