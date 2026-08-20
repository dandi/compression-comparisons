"""Provenance columns in report.parquet (plan §Phase 3.5 [R2-H2], [R2-H3]).

A stranger reading `report.parquet` must be able to tell a raw run from a
band-pass run, and one data version from another, without opening every
cell's `manifest.json`.
"""

from __future__ import annotations

import json

import pytest

from compbench.report.aggregate import _preprocessing_summary, load_cell


def _manifest(**provenance):
    return {"input": {"provenance": provenance}}


def test_no_preprocessing_reads_as_raw():
    assert _preprocessing_summary(_manifest()) == "raw"
    assert _preprocessing_summary(_manifest(preprocessing=[])) == "raw"
    assert _preprocessing_summary({}) == "raw"


def test_bandpass_is_rendered_with_its_band_and_order():
    m = _manifest(preprocessing=[{"kind": "bandpass", "low_hz": 300, "high_hz": 6000, "order": 4}])
    assert _preprocessing_summary(m) == "bandpass(300-6000Hz,o4)"


def test_raw_and_bandpass_partition_distinctly():
    """The column exists so `groupby` separates Fig 2 rows from Fig 7 rows."""
    raw = _preprocessing_summary(_manifest())
    bp = _preprocessing_summary(
        _manifest(preprocessing=[{"kind": "bandpass", "low_hz": 300, "high_hz": 6000, "order": 4}])
    )
    assert raw != bp


def test_unknown_step_kinds_still_render():
    m = _manifest(preprocessing=[{"kind": "notch", "hz": 50}])
    assert _preprocessing_summary(m) == "notch(hz=50)"


def test_chained_steps_are_joined():
    m = _manifest(
        preprocessing=[
            {"kind": "bandpass", "low_hz": 300, "high_hz": 6000, "order": 4},
            {"kind": "notch", "hz": 60},
        ]
    )
    assert _preprocessing_summary(m) == "bandpass(300-6000Hz,o4)+notch(hz=60)"


@pytest.fixture
def cell(tmp_path):
    def _make(manifest):
        (tmp_path / "metrics.json").write_text(json.dumps({"cr": 2.0}))
        (tmp_path / "manifest.json").write_text(json.dumps(manifest))
        return tmp_path

    return _make


def test_row_surfaces_annex_key_and_dataset_commit(cell):
    d = cell(
        {
            "input": {
                "provenance": {
                    "loader": "aind-benchmark",
                    "yaml_source": "configs/datasets/x.yaml",
                    "source": {"annex_key": "MD5E-s27648000000--abc", "dataset_commit": "deadbee"},
                    "preprocessing": [
                        {"kind": "bandpass", "low_hz": 300, "high_hz": 6000, "order": 4}
                    ],
                }
            }
        }
    )
    row = load_cell(d)
    assert row["input_annex_key"] == "MD5E-s27648000000--abc"
    assert row["input_dataset_commit"] == "deadbee"
    assert row["dataset_loader"] == "aind-benchmark"
    assert row["dataset_yaml_source"] == "configs/datasets/x.yaml"
    assert row["preprocessing_summary"] == "bandpass(300-6000Hz,o4)"


def test_row_tolerates_a_manifest_without_provenance(cell):
    """Older derivatives predate these fields; aggregation must not break."""
    row = load_cell(cell({"input": {}}))
    assert row["input_annex_key"] is None
    assert row["preprocessing_summary"] == "raw"
