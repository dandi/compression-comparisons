"""`datasets_matrix:` expansion — plan §Phase 3.5 [R5-H1].

Hand-listing `datasets:` does not scale to the paper's 16 recordings x N
preprocessing variants. These tests pin the cross-product semantics, the
strict-key validation, and the idempotence of the generated YAMLs.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from compbench.pipeline.profile import (
    expand_matrix,
    load_profile,
    materialize_datasets_matrix,
)


def _matrix(**over):
    base = {
        "loader": "aind-benchmark",
        "params": {"start_s": 0.0, "duration_s": 60.0},
        "recordings": [
            {"label": "rec-a", "params": {"path": "sourcedata/rec-a"}},
            {"label": "rec-b", "params": {"path": "sourcedata/rec-b"}},
        ],
        "preprocessing": [
            {"label": "raw"},
            {"label": "bp", "steps": [{"kind": "bandpass", "low_hz": 300, "high_hz": 6000}]},
        ],
    }
    base.update(over)
    return base


def _profile(matrix=None, datasets=None):
    raw = {"name": "t", "codecs": [{"codec": "lzma", "params": {"preset": 6}}]}
    if matrix is not None:
        raw["datasets_matrix"] = matrix
    if datasets is not None:
        raw["datasets"] = datasets
    return load_profile(raw)


def test_cross_product_cardinality(tmp_path):
    paths = materialize_datasets_matrix(_matrix(), tmp_path)
    assert len(paths) == 4  # 2 recordings x 2 preprocessing
    assert len({Path(p).name for p in paths}) == 4


def test_generated_yaml_content(tmp_path):
    materialize_datasets_matrix(_matrix(), tmp_path)
    bp = yaml.safe_load((tmp_path / "rec-a-bp.yaml").read_text())
    assert bp["loader"] == "aind-benchmark"
    # Matrix-wide params merge with the per-recording ones.
    assert bp["params"] == {"start_s": 0.0, "duration_s": 60.0, "path": "sourcedata/rec-a"}
    assert bp["preprocessing"] == [{"kind": "bandpass", "low_hz": 300, "high_hz": 6000}]

    raw = yaml.safe_load((tmp_path / "rec-a-raw.yaml").read_text())
    # A preprocessing entry with no `steps:` must not emit an empty block —
    # the yaml_loader's strict-key check would accept it, but `preprocessing: []`
    # reads as "steps were configured and did nothing", which is a lie.
    assert "preprocessing" not in raw


def test_per_recording_params_override_common(tmp_path):
    m = _matrix()
    m["recordings"][1]["params"]["duration_s"] = 10.0
    materialize_datasets_matrix(m, tmp_path)
    assert yaml.safe_load((tmp_path / "rec-b-raw.yaml").read_text())["params"]["duration_s"] == 10.0
    assert yaml.safe_load((tmp_path / "rec-a-raw.yaml").read_text())["params"]["duration_s"] == 60.0


def test_materialize_is_idempotent(tmp_path):
    materialize_datasets_matrix(_matrix(), tmp_path)
    target = tmp_path / "rec-a-raw.yaml"
    before = (target.read_text(), target.stat().st_mtime_ns)
    materialize_datasets_matrix(_matrix(), tmp_path)
    after = (target.read_text(), target.stat().st_mtime_ns)
    # Unchanged content must not even bump mtime — a resumed sweep should not
    # make Snakemake think the inputs moved.
    assert before == after


def test_preprocessing_optional_defaults_to_single_raw_variant(tmp_path):
    m = _matrix()
    del m["preprocessing"]
    paths = materialize_datasets_matrix(m, tmp_path)
    assert len(paths) == 2
    assert (tmp_path / "rec-a-raw.yaml").is_file()


def test_expand_matrix_cell_ids_name_recording_and_preprocessing(tmp_path):
    cells = list(expand_matrix(_profile(matrix=_matrix()), generated_dir=tmp_path))
    ids = {c.cell_id for c in cells}
    assert ids == {
        "rec-a-raw__lzma-preset_6",
        "rec-a-bp__lzma-preset_6",
        "rec-b-raw__lzma-preset_6",
        "rec-b-bp__lzma-preset_6",
    }


def test_explicit_datasets_and_matrix_compose(tmp_path):
    prof = _profile(matrix=_matrix(), datasets=["configs/datasets/synthetic-tiny.yaml"])
    cells = list(expand_matrix(prof, generated_dir=tmp_path))
    assert len(cells) == 5  # 1 explicit + 4 generated
    assert any(c.dataset_spec.endswith("synthetic-tiny.yaml") for c in cells)


def test_matrix_without_generated_dir_is_an_error():
    with pytest.raises(ValueError, match="generated_dir"):
        list(expand_matrix(_profile(matrix=_matrix())))


def test_profile_needs_datasets_or_matrix():
    with pytest.raises(ValueError, match="datasets_matrix"):
        load_profile({"name": "t", "codecs": [{"codec": "lzma"}]})


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda m: m.update(recording=m.pop("recordings")), "unknown key"),
        (lambda m: m.pop("loader"), "missing required `loader:`"),
        (lambda m: m.update(recordings=[]), "non-empty list"),
        (lambda m: m.update(recordings=[{"params": {"path": "x"}}]), "missing `label:`"),
        (
            lambda m: m.update(recordings=[{"label": "a", "path": "x"}]),
            "unknown key",
        ),
        (
            lambda m: m.update(recordings=[{"label": "a"}, {"label": "a"}]),
            "duplicate recording label",
        ),
        (
            lambda m: m.update(preprocessing=[{"label": "a"}, {"label": "a"}]),
            "duplicate preprocessing label",
        ),
        (lambda m: m.update(preprocessing=[{"steps": []}]), "missing `label:`"),
        (lambda m: m.update(preprocessing=[]), "non-empty list"),
    ],
)
def test_strict_key_and_shape_validation(mutate, match):
    m = _matrix()
    mutate(m)
    with pytest.raises(ValueError, match=match):
        _profile(matrix=m)
