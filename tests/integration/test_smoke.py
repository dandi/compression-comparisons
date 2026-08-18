"""End-to-end smoke: `duct compbench run …` → `compbench report …` → Parquet row.

Requires `duct` and `compbench` on PATH. Skipped if either is missing so
that unit-only test runs stay usable.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

DUCT = shutil.which("duct")
COMPBENCH = shutil.which("compbench")

pytestmark = pytest.mark.integration


@pytest.fixture
def cell_dir(tmp_path: Path) -> Path:
    return tmp_path / "cell-0"


@pytest.mark.ai_generated
@pytest.mark.skipif(DUCT is None, reason="`duct` not on PATH")
@pytest.mark.skipif(COMPBENCH is None, reason="`compbench` not on PATH")
def test_smoke_duct_wraps_compbench(cell_dir: Path) -> None:
    assert DUCT and COMPBENCH  # for mypy
    cell_dir.mkdir(parents=True)
    proc = subprocess.run(
        [
            DUCT,
            "--output-prefix",
            f"{cell_dir}/duct-",
            "--sample-interval",
            "1",
            "--report-interval",
            "1",
            COMPBENCH,
            "run",
            "--input",
            "synthetic:duration_s=0.5,sample_rate_hz=2000,n_channels=4,seed=1",
            "--codec",
            "blosc-zstd",
            "--codec-params",
            "level=5,shuffle=byte",
            "--output-dir",
            str(cell_dir),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f"stderr:\n{proc.stderr}\nstdout:\n{proc.stdout}"

    # compbench artifacts
    metrics = json.loads((cell_dir / "metrics.json").read_text())
    manifest = json.loads((cell_dir / "manifest.json").read_text())
    assert metrics["round_trip_ok"] is True
    assert metrics["rmse"] == 0.0
    assert metrics["cr"] > 0
    assert manifest["input"]["n_channels"] == 4
    assert manifest["codec"]["name"] == "blosc-zstd"

    # con-duct artifacts
    info_path = cell_dir / "duct-info.json"
    assert info_path.exists(), f"duct info missing; dir contents: {list(cell_dir.iterdir())}"
    info = json.loads(info_path.read_text())
    summary = info["execution_summary"]
    assert summary["exit_code"] == 0
    assert summary["wall_clock_time"] > 0


@pytest.mark.ai_generated
@pytest.mark.skipif(DUCT is None, reason="`duct` not on PATH")
@pytest.mark.skipif(COMPBENCH is None, reason="`compbench` not on PATH")
def test_report_aggregator_joins_metrics_and_duct(tmp_path: Path) -> None:
    """Run one duct-wrapped compbench cell, then `compbench report` → row with
    both metric_* and duct_* fields, plus derived_xrt_duct."""
    assert DUCT and COMPBENCH  # for mypy
    results = tmp_path / "results"
    cell = results / "cell-only"
    cell.mkdir(parents=True)
    subprocess.run(
        [
            DUCT,
            "--output-prefix",
            f"{cell}/duct-",
            "--sample-interval",
            "1",
            "--report-interval",
            "1",
            COMPBENCH,
            "run",
            "--input",
            "synthetic:duration_s=0.5,sample_rate_hz=2000,n_channels=4,seed=1",
            "--codec",
            "blosc-zstd",
            "--output-dir",
            str(cell),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    out = tmp_path / "rows.jsonl"
    proc = subprocess.run(
        [COMPBENCH, "report", "--results-dir", str(results), "--output", str(out)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    lines = out.read_text().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["metric_round_trip_ok"] is True
    assert row["codec_name"] == "blosc-zstd"
    assert row["duct_wall_time_s"] is not None
    assert row["duct_wall_time_s"] > 0
    assert "derived_xrt_duct" in row
