"""The sorting report must not mislead about what it is showing."""

import json
from pathlib import Path

import pytest

from compbench.report.sorting import render_sorting_markdown


def _arm(root: Path, name: str, *, cr: float, exact: bool, params: dict,
         well: int, fp: int, acc: float) -> None:
    d = root / name
    d.mkdir()
    (d / "compress-metrics.json").write_text(json.dumps({
        "cr": cr, "round_trip_exact": exact,
        "codec": {"name": params.pop("_codec", "t261"), "params": params},
    }))
    (d / "sorting-metrics.json").write_text(json.dumps({
        "pooled": {"accuracy": acc, "recall": acc, "precision": acc},
        "unit_counts": {"num_well_detected": well, "num_false_positive": fp,
                        "num_redundant": 0, "num_gt": 100, "num_sorter": well + fp},
    }))


@pytest.fixture
def sweep(tmp_path: Path) -> Path:
    _arm(tmp_path, "a", cr=2.9, exact=True,
         params={"_codec": "blosc-zstd", "level": 9}, well=87, fp=31, acc=0.9)
    _arm(tmp_path, "b", cr=3.7, exact=True,
         params={"preset": "combinedPresetEEG_IndepChannel_lossless"}, well=87, fp=31, acc=0.9)
    _arm(tmp_path, "c-hash", cr=8.6, exact=False,
         params={"preset": "combinedPresetEEG_IndepChannel", "step_size_for_qp": 5.0},
         well=81, fp=41, acc=0.91)
    return tmp_path


def test_lossless_detected_from_measurement_not_name(sweep: Path) -> None:
    """`blosc-zstd level 9` is lossless and says so nowhere in its name."""
    body = render_sorting_markdown(sweep)
    assert "3 lossless arms" not in body   # only two here
    assert "2 lossless arms" in body


def test_arm_labelled_by_its_varying_parameter_not_a_hash(sweep: Path) -> None:
    body = render_sorting_markdown(sweep)
    assert "t261 QP 5.0" in body
    assert "c-hash" not in body


def test_unit_counts_precede_accuracy(sweep: Path) -> None:
    """Accuracy can rise while the sorting degrades, so it must not lead."""
    header = next(l for l in body_lines(sweep) if l.startswith("| arm"))
    cols = [c.strip() for c in header.strip("|").split("|")]
    assert cols.index("well detected") < cols.index("accuracy")


def test_degrading_arm_shows_negative_delta(sweep: Path) -> None:
    body = render_sorting_markdown(sweep)
    assert "-6 well, +10 FP" in body


def body_lines(sweep: Path):
    return render_sorting_markdown(sweep).splitlines()
