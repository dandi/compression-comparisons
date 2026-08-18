"""Unit tests for compbench.report.aggregate."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from compbench.report import aggregate_directory, load_cell, load_duct_info, write_parquet


def _write_cell(d: Path, metrics: dict[str, Any], manifest: dict[str, Any] | None = None) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / "metrics.json").write_text(json.dumps(metrics))
    if manifest is not None:
        (d / "manifest.json").write_text(json.dumps(manifest))


def _write_duct_info(d: Path, summary: dict[str, Any], prefix: str = "duct-") -> Path:
    p = d / f"{prefix}info.json"
    p.write_text(json.dumps({"execution_summary": summary}))
    return p


@pytest.mark.ai_generated
def test_load_cell_missing_metrics(tmp_path: Path) -> None:
    assert load_cell(tmp_path) is None


@pytest.mark.ai_generated
def test_load_cell_no_duct(tmp_path: Path) -> None:
    _write_cell(
        tmp_path,
        metrics={"cr": 3.5, "rmse": 0.0, "round_trip_ok": True},
        manifest={
            "codec": {"name": "blosc-zstd", "lossy": False},
            "input": {
                "nbytes": 1024,
                "duration_s": 1.0,
                "sample_rate_hz": 1000,
                "n_channels": 4,
                "dtype": "int16",
                "sha256": "abc",
            },
            "compbench_version": "0.0.1",
            "git_sha": "deadbeef",
            "created_utc": "2026-08-18T00:00:00+00:00",
        },
    )
    row = load_cell(tmp_path)
    assert row is not None
    assert row["metric_cr"] == 3.5
    assert row["codec_name"] == "blosc-zstd"
    assert row["input_n_channels"] == 4
    assert "duct_wall_time_s" not in row


@pytest.mark.ai_generated
def test_load_cell_with_duct(tmp_path: Path) -> None:
    _write_cell(
        tmp_path,
        metrics={"cr": 5.0},
        manifest={"input": {"duration_s": 10.0}, "codec": {"name": "x"}},
    )
    _write_duct_info(
        tmp_path,
        {
            "wall_clock_time": 2.0,
            "peak_rss": 1024 * 1024,
            "average_rss": 512 * 1024,
            "peak_vsz": 4096 * 1024,
            "average_vsz": 2048 * 1024,
            "peak_pcpu": 90.0,
            "average_pcpu": 45.0,
            "exit_code": 0,
            "num_samples": 4,
            "start_time": 100.0,
            "end_time": 102.0,
        },
    )
    row = load_cell(tmp_path)
    assert row is not None
    assert row["duct_wall_time_s"] == 2.0
    assert row["duct_peak_rss_bytes"] == 1024 * 1024
    assert row["derived_xrt_duct"] == pytest.approx(5.0)  # 10s / 2s


@pytest.mark.ai_generated
def test_load_cell_ignores_metrics_and_manifest_as_duct(tmp_path: Path) -> None:
    """Regression: `metrics.json` and `manifest.json` both end in `info.json`? No —
    but they do end in `json`. Ensure we don't mistake them for duct info by
    using a suffix that *is* shared with duct's file naming.
    """
    _write_cell(tmp_path, metrics={"cr": 1.0}, manifest={"codec": {"name": "x"}})
    # No duct file created; loader should not confuse our files with duct's.
    row = load_cell(tmp_path)
    assert row is not None
    assert "duct_wall_time_s" not in row


@pytest.mark.ai_generated
def test_aggregate_directory_walks_nested_cells(tmp_path: Path) -> None:
    for i in range(3):
        cell = tmp_path / "profile-A" / f"cell-{i}"
        _write_cell(cell, metrics={"cr": float(i + 1)}, manifest={"codec": {"name": "x"}})
    for i in range(2):
        cell = tmp_path / "profile-B" / f"cell-{i}"
        _write_cell(cell, metrics={"cr": float(i + 10)}, manifest={"codec": {"name": "y"}})
    rows = aggregate_directory(tmp_path)
    assert len(rows) == 5
    cr_values = sorted(r["metric_cr"] for r in rows)
    assert cr_values == [1.0, 2.0, 3.0, 10.0, 11.0]


@pytest.mark.ai_generated
def test_aggregate_directory_empty(tmp_path: Path) -> None:
    assert aggregate_directory(tmp_path) == []


@pytest.mark.ai_generated
def test_write_parquet_roundtrip(tmp_path: Path) -> None:
    import pyarrow.parquet as pq

    rows = [{"a": 1, "b": "hello"}, {"a": 2, "c": 3.14}]
    out = tmp_path / "out.parquet"
    write_parquet(rows, out)
    tab = pq.read_table(out)
    assert tab.num_rows == 2
    # Padded columns present as nulls where missing.
    d = tab.to_pydict()
    assert set(d) == {"a", "b", "c"}


@pytest.mark.ai_generated
def test_write_parquet_empty(tmp_path: Path) -> None:
    import pyarrow.parquet as pq

    out = tmp_path / "empty.parquet"
    write_parquet([], out)
    tab = pq.read_table(out)
    assert tab.num_rows == 0


@pytest.mark.ai_generated
def test_load_duct_info_partial(tmp_path: Path) -> None:
    """Older/newer duct schema may add/drop fields — loader must not KeyError."""
    p = tmp_path / "duct-info.json"
    p.write_text(json.dumps({"execution_summary": {"wall_clock_time": 1.0}}))
    d = load_duct_info(p)
    assert d["duct_wall_time_s"] == 1.0
    assert d["duct_peak_rss_bytes"] is None
