"""`report.parquet` must be joinable against the paper's own results.

The Phase 1 gate compares "(recording x codec x exactly-matched config)".
Until these columns existed, the only carrier of the config was the
`cell_dir` slug — so the gate was not mechanically evaluable, and a silent
condition mismatch (the failure mode this project keeps hitting) could not
be detected by a join at all.
"""

from __future__ import annotations

import json

import pytest

from compbench.report.aggregate import load_cell


def _cell(tmp_path, codec, provenance=None, metrics=None):
    (tmp_path / "metrics.json").write_text(json.dumps({"cr": 2.0, **(metrics or {})}))
    (tmp_path / "manifest.json").write_text(
        json.dumps({"codec": codec, "input": {"provenance": provenance or {}}})
    )
    return load_cell(tmp_path)


def test_every_codec_param_becomes_its_own_column(tmp_path):
    row = _cell(tmp_path, {"name": "lzma", "params": {"preset": 9, "shuffle": "no"}})
    assert row["codec_param_preset"] == 9
    assert row["codec_param_shuffle"] == "no"


def test_filters_are_surfaced_because_they_change_bytes_not_names(tmp_path):
    """A delta or shuffle filter changes the compressed bytes while the codec
    name stays identical — exactly what makes two cells silently
    incomparable."""
    row = _cell(
        tmp_path,
        {
            "name": "blosc-zstd",
            "params": {"level": 9, "shuffle": "bit", "delta": "2d-time"},
            "filters": [{"id": "compbench.delta2d", "axis": 0}],
        },
    )
    assert row["codec_param_delta"] == "2d-time"
    assert "compbench.delta2d" in row["codec_filters"]


def test_no_filters_reads_as_null_not_empty_string(tmp_path):
    row = _cell(tmp_path, {"name": "lzma", "params": {"preset": 9}})
    assert row["codec_filters"] is None


@pytest.mark.parametrize(
    ("folder", "source", "probe"),
    [
        ("CSHZAD026_2020-09-04_probe00", "IBL", "NP1"),
        ("625749_2022-08-03_15-15-06_ProbeA", "AIND", "NP1"),
        ("621362_2022-07-14_11-19-36_ProbeA", "AIND", "NP2"),
        ("mearec_NP1.h5", "MEArec", "NP1"),
    ],
)
def test_recording_source_and_probe_resolve(tmp_path, folder, source, probe):
    """Probe type decides which reference rows a cell may be joined against,
    and it is not derivable from anything else in the manifest."""
    row = _cell(
        tmp_path,
        {"name": "lzma", "params": {"preset": 9}},
        {"spikeinterface": {"folder_name": folder}},
    )
    assert row["recording"] == folder
    assert row["recording_source"] == source
    assert row["probe"] == probe


def test_recording_falls_back_to_the_path_basename(tmp_path):
    row = _cell(
        tmp_path,
        {"name": "lzma", "params": {"preset": 9}},
        {"params": {"path": "sourcedata/x/ibl-np1/CSHZAD029_2020-09-09_probe00"}},
    )
    assert row["recording"] == "CSHZAD029_2020-09-09_probe00"
    assert row["probe"] == "NP1"


def test_unknown_recording_is_null_not_guessed(tmp_path):
    row = _cell(
        tmp_path,
        {"name": "lzma", "params": {"preset": 9}},
        {"spikeinterface": {"folder_name": "some-other-dataset"}},
    )
    assert row["recording"] == "some-other-dataset"
    assert row["recording_source"] is None
    assert row["probe"] is None


def test_reproducibility_relevant_codec_state_is_carried(tmp_path):
    """blosc thread count decides byte-reproducibility; the wavpack version
    decides which hybrid bitstream was emitted."""
    row = _cell(
        tmp_path,
        {
            "name": "wavpack",
            "params": {"level": 2, "bps": 2.25},
            "blosc_nthreads": 1,
            "wavpack_numcodecs_version": "0.2.3",
        },
    )
    assert row["codec_blosc_nthreads"] == 1
    assert row["codec_wavpack_numcodecs_version"] == "0.2.3"


def test_gate_join_dimensions_are_all_present(tmp_path):
    """The full key the Phase 1 gate needs, in one place."""
    row = _cell(
        tmp_path,
        {"name": "blosc-zstd", "params": {"level": 9, "shuffle": "bit"}},
        {
            "spikeinterface": {"folder_name": "CSHZAD026_2020-09-04_probe00"},
            "preprocessing": [{"kind": "bandpass", "low_hz": 300, "high_hz": 6000, "order": 5}],
        },
        metrics={"chunk_duration_s": 1.0},
    )
    for key in (
        "recording",
        "probe",
        "recording_source",
        "codec_name",
        "codec_param_level",
        "codec_param_shuffle",
        "preprocessing_summary",
        "metric_chunk_duration_s",
    ):
        assert key in row, f"missing join dimension: {key}"
