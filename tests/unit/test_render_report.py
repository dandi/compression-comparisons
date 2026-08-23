"""Unit tests for the Markdown render_report."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from compbench.cli import main
from compbench.report import render_from_parquet, render_markdown, write_parquet


@pytest.mark.ai_generated
def test_render_markdown_empty() -> None:
    body = render_markdown([])
    assert "0 total" in body
    assert "no cells" in body.lower() or "—" in body


@pytest.mark.ai_generated
def test_render_markdown_sorts_by_cr_desc() -> None:
    rows = [
        {
            "codec_name": "a",
            "codec_lossy": False,
            "metric_cr": 1.5,
            "metric_encode_xrt": 10.0,
            "metric_decode_xrt": 20.0,
            "metric_rmse": 0.0,
            "metric_round_trip_ok": True,
            "duct_wall_time_s": 1.0,
            "duct_peak_rss_bytes": 1_000_000_000,
            "cell_dir": "x/y__a-l3",
        },
        {
            "codec_name": "b",
            "codec_lossy": False,
            "metric_cr": 3.0,
            "metric_encode_xrt": 5.0,
            "metric_decode_xrt": 100.0,
            "metric_rmse": 0.0,
            "metric_round_trip_ok": True,
            "duct_wall_time_s": 2.0,
            "duct_peak_rss_bytes": 2_000_000_000,
            "cell_dir": "x/y__b-l9",
        },
    ]
    body = render_markdown(rows)
    # b (CR=3) should appear before a (CR=1.5) in the table body.
    # Cells are space-padded for readability (CLAUDE.md), so match on the
    # stripped cell rather than on incidental formatting.
    order = [
        [c.strip() for c in line.strip().strip("|").split("|")][3]
        for line in body.splitlines()
        if line.startswith("|") and not set(line) <= set("|-: ")
    ]
    assert order.index("b") < order.index("a")


@pytest.mark.ai_generated
def test_render_markdown_highlights_best() -> None:
    rows = [
        {"codec_name": "ll1", "codec_lossy": False, "metric_cr": 2.0, "cell_dir": "x/y__ll1"},
        {"codec_name": "ll2", "codec_lossy": False, "metric_cr": 3.5, "cell_dir": "x/y__ll2"},
        {
            "codec_name": "loss1",
            "codec_lossy": True,
            "metric_cr": 10.0,
            "metric_rmse": 1.5,
            "cell_dir": "x/y__loss1",
        },
    ]
    body = render_markdown(rows)
    assert "Best lossless" in body and "ll2" in body
    assert "Best lossy CR" in body and "loss1" in body


@pytest.mark.ai_generated
def test_render_from_parquet_roundtrip(tmp_path: Path) -> None:
    rows = [
        {
            "codec_name": "blosc-zstd",
            "codec_lossy": False,
            "metric_cr": 2.3,
            "metric_encode_xrt": 5.5,
            "metric_decode_xrt": 100.0,
            "metric_rmse": 0.0,
            "metric_round_trip_ok": True,
            "duct_wall_time_s": 15.0,
            "duct_peak_rss_bytes": 2 * 1024**3,
            "cell_dir": "out/synthetic__blosc-zstd-level_3",
        },
    ]
    parquet = tmp_path / "report.parquet"
    write_parquet(rows, parquet)
    out = tmp_path / "RESULTS.md"
    render_from_parquet(parquet, out, title="test")
    body = out.read_text()
    assert "# test" in body
    assert "blosc-zstd" in body
    assert "2.3" in body


@pytest.mark.ai_generated
def test_render_report_cli_end_to_end(tmp_path: Path) -> None:
    """CLI wiring: `compbench render-report` produces the file."""
    rows = [
        {
            "codec_name": "t261",
            "codec_lossy": True,
            "metric_cr": 9.0,
            "metric_rmse": 1.4,
            "cell_dir": "x/y__t261-qp5",
        },
    ]
    parquet = tmp_path / "report.parquet"
    write_parquet(rows, parquet)
    out = tmp_path / "results.md"
    r = CliRunner().invoke(
        main,
        [
            "render-report",
            "--parquet",
            str(parquet),
            "--output",
            str(out),
            "--title",
            "Real ephys reproduction",
            "--source-note",
            "10 s slice of CSHZAD026.",
        ],
    )
    assert r.exit_code == 0, r.output
    body = out.read_text()
    assert "Real ephys reproduction" in body
    assert "10 s slice of CSHZAD026" in body
    assert "t261" in body


@pytest.mark.ai_generated
def test_render_partial_row_no_crash(tmp_path: Path) -> None:
    """Missing fields (e.g., no duct-info found) render as em-dash."""
    rows = [
        {
            "codec_name": "x",
            "codec_lossy": False,
            "metric_cr": 2.0,
            "cell_dir": "d/y__x",
        },  # no duct fields
    ]
    body = render_markdown(rows)
    # padded for readability (CLAUDE.md) -- assert on the cell, not its padding
    cells = {
        c.strip()
        for line in body.splitlines()
        if line.startswith("|")
        for c in line.strip().strip("|").split("|")
    }
    assert "x" in cells
    assert body.count("—") >= 1  # some fields default to em-dash
