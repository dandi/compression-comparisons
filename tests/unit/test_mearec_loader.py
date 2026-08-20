"""Skeleton tests for the MEArec loader — the real file is 19 GB annexed so
we test only path-not-found + registry membership. Full end-to-end tests
land when the sorting-eval pipeline (Phase 3.5 R1-H3) lands.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("spikeinterface")

from compbench import datasets
from compbench.datasets import mearec


@pytest.mark.ai_generated
def test_mearec_scheme_registered() -> None:
    assert "mearec" in datasets.schemes()


@pytest.mark.ai_generated
def test_mearec_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        mearec.load_mearec(tmp_path / "nowhere.h5")


@pytest.mark.ai_generated
def test_mearec_metric_skeleton_stubs_raise() -> None:
    """Sorting-metric skeletons raise NotImplementedError until Phase 3.5."""
    from compbench.metrics import sorting

    for fn in (
        sorting.gt_comparison_metrics,
        sorting.sorting_agreement,
        sorting.unit_classification,
        sorting.qc_pass_fraction,
        sorting.waveform_feature_errors,
    ):
        with pytest.raises(NotImplementedError, match="Phase 3.5"):
            fn(None, None)  # type: ignore[arg-type]
