"""Renderer behaviour once a sweep spans more than one recording.

The single-recording table had no dataset or preprocessing column — at the
448 cells of `paper-real-np1-8` every row would then look identical apart
from the codec params. The median section is the shape the Phase 1 gate is
stated in (plan §5): the paper reports a distribution over its recordings,
so the comparable figure is a median across them.
"""

from __future__ import annotations

from compbench.report.render import render_markdown


def _row(dataset, codec, params, cr, preproc="raw", **extra):
    row = {
        "cell_dir": f"derivatives/sweep/{dataset}__{codec}-{params}",
        "codec_name": codec,
        "metric_cr": cr,
        "preprocessing_summary": preproc,
        "codec_lossy": False,
    }
    row.update(extra)
    return row


def _has_row(body: str, *cells: str) -> bool:
    """Is there a table row with exactly these cell values?

    Tables are space-padded for readability (CLAUDE.md), so compare stripped
    cells rather than a literal `| a | b |` substring.
    """
    want = list(cells)
    for line in body.splitlines():
        if not line.startswith("|"):
            continue
        got = [c.strip() for c in line.strip().strip("|").split("|")]
        if got[: len(want)] == want:
            return True
    return False


def _has_cell(body: str, value: str) -> bool:
    """Does any table row contain a cell with exactly this value?"""
    for line in body.splitlines():
        if not line.startswith("|"):
            continue
        if value in [c.strip() for c in line.strip().strip("|").split("|")]:
            return True
    return False


def test_single_dataset_sweep_has_no_median_section():
    body = render_markdown([_row("recA", "lzma", "preset_6", 3.0)])
    assert "Median CR across" not in body


def test_multi_dataset_sweep_reports_median_min_max_and_n():
    rows = [
        _row("recA", "lzma", "preset_6", 3.0),
        _row("recB", "lzma", "preset_6", 4.0),
        _row("recC", "lzma", "preset_6", 5.0),
    ]
    body = render_markdown(rows)
    assert "Median CR across 3 datasets" in body
    # median 4.000, min 3.000, max 5.000, n 3
    assert _has_row(body, "raw @ whole", "lzma", "lzma-preset_6", "4.000", "3.000", "5.000", "3")


def test_median_is_computed_per_preprocessing_variant():
    """Raw and band-pass must not be pooled — they are different figures."""
    rows = [
        _row("recA", "lzma", "preset_6", 3.0, preproc="raw"),
        _row("recB", "lzma", "preset_6", 3.0, preproc="raw"),
        _row("recA", "lzma", "preset_6", 9.0, preproc="bandpass(300-6000Hz,o4)"),
        _row("recB", "lzma", "preset_6", 9.0, preproc="bandpass(300-6000Hz,o4)"),
    ]
    body = render_markdown(rows)
    assert _has_row(body, "raw @ whole", "lzma", "lzma-preset_6", "3.000")
    assert _has_row(body, "bandpass(300-6000Hz,o4) @ whole", "lzma", "lzma-preset_6", "9.000")


def test_short_n_is_visible_when_cells_are_missing():
    """A codec that failed on half the recordings must not look complete."""
    rows = [
        _row("recA", "lzma", "preset_6", 3.0),
        _row("recB", "lzma", "preset_6", 4.0),
        _row("recA", "t261", "qp1.5", 8.0),
    ]
    body = render_markdown(rows)
    assert _has_row(body, "raw @ whole", "t261", "t261-qp1.5", "8.000", "8.000", "8.000", "1")


def test_main_table_carries_dataset_and_preprocessing():
    body = render_markdown(
        [_row("ibl-CSHZAD026-bp", "lzma", "preset_6", 3.0, preproc="bandpass(300-6000Hz,o4)")]
    )
    assert _has_row(body, "dataset", "preproc", "chunk", "codec")
    assert "ibl-CSHZAD026-bp" in body
    assert "bandpass(300-6000Hz,o4)" in body


def test_band_limited_rmse_and_per_channel_prdn_are_surfaced():
    body = render_markdown(
        [
            _row(
                "recA",
                "t261",
                "qp1.5",
                8.76,
                codec_lossy=True,
                metric_rmse=0.4055,
                metric_rmse_band_limited_300_6000=0.2500,
                metric_prdn_per_channel_median_percent=8.63,
            )
        ]
    )
    assert "RMSE_bp" in body and "PRDN/ch %" in body
    assert "0.2500" in body
    assert "8.63" in body


def test_pre_r2h3_rows_without_preprocessing_column_read_as_raw():
    """The three derivatives already in the study predate the column."""
    row = _row("recA", "lzma", "preset_6", 3.0)
    del row["preprocessing_summary"]
    body = render_markdown([row])
    assert _has_cell(body, "raw")


def test_output_is_stable_across_repeated_renders():
    """DEPLOY promises the Markdown is idempotent."""
    rows = [
        _row("recB", "zstd", "level_22", 3.1),
        _row("recA", "lzma", "preset_6", 3.4),
        _row("recA", "zstd", "level_22", 3.0),
        _row("recB", "lzma", "preset_6", 3.3),
    ]
    assert render_markdown(rows) == render_markdown(list(reversed(rows)))


def test_chunking_partitions_the_median_section():
    """A whole-buffer CR and a 1 s CR are different conditions and must never
    be pooled into one median — see plan §4.6b(b)."""
    rows = [
        _row("recA", "lzma", "preset_6", 9.0, metric_chunk_duration_s=None),
        _row("recB", "lzma", "preset_6", 9.0, metric_chunk_duration_s=None),
        _row("recA", "lzma", "preset_6", 3.0, metric_chunk_duration_s=1.0),
        _row("recB", "lzma", "preset_6", 3.0, metric_chunk_duration_s=1.0),
    ]
    body = render_markdown(rows)
    assert _has_row(body, "raw @ whole", "lzma", "lzma-preset_6", "9.000")
    assert _has_row(body, "raw @ 1s", "lzma", "lzma-preset_6", "3.000")


def test_whole_buffer_is_labelled_not_blank():
    """A blank would read as 'not applicable' rather than 'not comparable'."""
    body = render_markdown([_row("recA", "lzma", "preset_6", 3.0)])
    assert "whole" in body


def test_lsb_correction_appears_in_the_preprocessing_label():
    from compbench.report.aggregate import _preprocessing_summary

    m = {
        "input": {
            "provenance": {
                "preprocessing": [
                    {"kind": "lsb_correction", "lsb": 12},
                    {"kind": "bandpass", "low_hz": 300, "high_hz": 6000, "order": 4},
                ]
            }
        }
    }
    assert _preprocessing_summary(m) == "lsb12+bandpass(300-6000Hz,o4)"
