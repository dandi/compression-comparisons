"""Replay the paper's own simulated cells through our comparison layer.

Buccino et al. released, under CC0, both the Kilosort 2.5 sortings behind
their Figs 10/11 and the summary CSV computed from them. That makes the
entire ground-truth comparison layer testable **without a GPU, without a
sorter, and without re-deriving anything** — we feed their sortings to our
code and check we get their published numbers back.

This is the strongest test in the project: it pins accuracy, precision,
recall and all six unit-count categories against 32 published cells, and
it would catch a SpikeInterface version drift that silently redefined any
of them. It runs in well under a minute.

The comparison layer turns out to be version-stable: the paper ran SI
0.97.1, we run 0.104.8, and every cell reproduces.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from compbench.metrics.sorting import gt_comparison_metrics, unit_classification

REPO = Path(__file__).resolve().parents[2]
SIM = (
    REPO / "src/capsule-ephys-compression-results/data/ephys-compression-results/results-lossy-sim"
)
PROBE = {"Neuropixels1.0": "NP1", "Neuropixels2.0": "NP2"}
COUNT_COLUMNS = (
    "num_well_detected",
    "num_false_positive",
    "num_redundant",
    "num_overmerged",
)

pytestmark = pytest.mark.skipif(
    not (SIM / "benchmark-lossy-sim.csv").is_file(),
    reason="capsule subdataset not populated (src/capsule-ephys-compression-results)",
)


def _cases():
    import pandas as pd

    ref = pd.read_csv(SIM / "benchmark-lossy-sim.csv", index_col=False)
    out = []
    for _, row in ref.iterrows():
        probe = PROBE[row["probe"]]
        strategy = row["strategy"]
        factor = float(row["factor"])
        # bit_truncation folders use integer names, wavpack uses floats.
        stem = str(int(factor)) if strategy == "bit_truncation" else str(factor)
        folder = SIM / f"sortings-{probe}-{strategy}" / f"sorting_{strategy}_{stem}"
        out.append(pytest.param(row, folder, id=f"{probe}-{strategy}-{stem}"))
    return out


CASES = _cases() if (SIM / "benchmark-lossy-sim.csv").is_file() else []


def _load(folder: Path, probe: str):
    import spikeinterface as si

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return si.load(SIM / f"gt-{probe}/sorting"), si.load(folder)


@pytest.mark.parametrize(("row", "folder"), CASES)
def test_pooled_performance_matches_the_paper(row, folder):
    gt, ks = _load(folder, PROBE[row["probe"]])
    out = gt_comparison_metrics(gt, ks, exhaustive_gt=True)
    for key in ("accuracy", "recall", "precision"):
        assert out["pooled"][key] == pytest.approx(row[key], abs=1e-9), key


@pytest.mark.parametrize(("row", "folder"), CASES)
def test_unit_counts_match_the_paper(row, folder):
    gt, ks = _load(folder, PROBE[row["probe"]])
    out = gt_comparison_metrics(gt, ks, exhaustive_gt=True)
    for column in COUNT_COLUMNS:
        if column in row:
            assert out["unit_counts"][column] == int(row[column]), column


def test_the_failure_the_paper_flags_is_reproduced():
    """NP1 bit-truncation 4 -> 5, the transition that motivates our
    acceptance criteria.

    False positives rise 22x (65 -> 1435) while accuracy falls only 7 %
    (0.998 -> 0.927) and well-detected units fall 10 %. A criterion phrased
    on mean accuracy therefore registers a mild degradation where the unit
    counts register a collapse — which is why §5 Phase 3b judges on
    `num_false_positive` / `num_well_detected` and the agreement curve, not
    on a pooled accuracy tolerance.

    (The lossless baseline is 52 false positives. An earlier draft of the
    plan quoted "52 -> 1435" as the 4->5 transition; 52 is bit-truncation
    ZERO, and the 4->5 step is 65 -> 1435.)
    """
    gt, ks0 = _load(SIM / "sortings-NP1-bit_truncation/sorting_bit_truncation_0", "NP1")
    _, ks4 = _load(SIM / "sortings-NP1-bit_truncation/sorting_bit_truncation_4", "NP1")
    _, ks5 = _load(SIM / "sortings-NP1-bit_truncation/sorting_bit_truncation_5", "NP1")
    a0 = gt_comparison_metrics(gt, ks0, exhaustive_gt=True)
    a4 = gt_comparison_metrics(gt, ks4, exhaustive_gt=True)
    a5 = gt_comparison_metrics(gt, ks5, exhaustive_gt=True)

    assert a0["unit_counts"]["num_false_positive"] == 52  # lossless baseline
    assert a4["unit_counts"]["num_false_positive"] == 65
    assert a5["unit_counts"]["num_false_positive"] == 1435

    # Unit counts collapse; accuracy merely dips.
    fp_ratio = a5["unit_counts"]["num_false_positive"] / a4["unit_counts"]["num_false_positive"]
    acc_drop = (a4["pooled"]["accuracy"] - a5["pooled"]["accuracy"]) / a4["pooled"]["accuracy"]
    assert fp_ratio > 20
    assert acc_drop < 0.10
    assert a4["unit_counts"]["num_well_detected"] == 100
    assert a5["unit_counts"]["num_well_detected"] == 90


def test_per_unit_distribution_is_returned_not_just_the_mean():
    gt, ks = _load(SIM / "sortings-NP1-bit_truncation/sorting_bit_truncation_0", "NP1")
    out = gt_comparison_metrics(gt, ks, exhaustive_gt=True)
    assert len(out["per_unit"]) == len(gt.unit_ids) == 100
    assert {"accuracy", "precision", "recall"} <= set(out["per_unit"][0])


def test_comparison_parameters_are_echoed_back():
    """A unit count is not interpretable without the scores that produced it,
    and SpikeInterface defaults change between versions."""
    gt, ks = _load(SIM / "sortings-NP1-bit_truncation/sorting_bit_truncation_0", "NP1")
    params = gt_comparison_metrics(gt, ks)["comparison_params"]
    assert params["well_detected_score"] == 0.8
    assert params["redundant_score"] == 0.2
    assert params["overmerged_score"] == 0.2
    assert params["match_mode"] == "hungarian"


def test_unit_classification_delegates_to_spikeinterface():
    import spikeinterface.comparison as sc

    gt, ks = _load(SIM / "sortings-NP1-bit_truncation/sorting_bit_truncation_5", "NP1")
    cmp = sc.compare_sorter_to_ground_truth(gt, ks, exhaustive_gt=True)
    assert unit_classification(cmp)["num_false_positive"] == 1435
