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
def test_no_sorting_metric_is_still_a_stub() -> None:
    """Every function in the sorting contract is implemented.

    This replaces a guard that asserted the opposite -- that the five
    Phase 3.5 metrics still raised NotImplementedError, so the list could
    not go stale while they were skeletons. They landed on 2026-08-24, so
    the guard now runs the other way: nothing may regress to a stub, and a
    newly added metric cannot be shipped as one.
    """
    import inspect

    from compbench.metrics import sorting

    stubs = [
        name
        for name in sorting.__all__
        if "NotImplementedError" in inspect.getsource(getattr(sorting, name))
    ]
    assert not stubs, f"still stubs: {stubs}"


@pytest.mark.ai_generated
def test_waveform_features_use_the_papers_definition() -> None:
    """Fig 14 must not be judged with SI >= 0.104's half_width.

    0.97.1 takes the OUTERMOST half-amplitude crossings; 0.104 takes the
    ones adjacent to the trough, and over the paper's own NP1 templates the
    p90 relative difference is 57 % -- five times the 10 % line Fig 14 is
    judged against. The implementation therefore computes the features
    itself and stamps which definition it used.
    """
    import inspect

    from compbench.metrics import sorting

    src = inspect.getsource(sorting.waveform_feature_errors)
    assert "buccino2023/spikeinterface-0.97.1" in src
    # it must NOT delegate to the installed version's renamed metric
    assert "compute_template_metrics" not in src
    # upsampling must actually be used, not merely accepted: these features
    # come from sample indices and are otherwise quantised to ~10 % steps
    assert "upsampling_factor" in src and "_upsample" in src


@pytest.mark.ai_generated
def test_implemented_sorting_metrics_are_callable() -> None:
    """The complement: these are no longer stubs."""
    from compbench.metrics import sorting

    for fn in (sorting.gt_comparison_metrics, sorting.unit_classification):
        assert "NotImplementedError" not in (fn.__doc__ or "")


@pytest.mark.ai_generated
def test_curation_thresholds_match_the_papers_driver() -> None:
    """CRITICAL correction: the driver says ISI < 0.5 and presence > 0.95.

    An earlier revision recorded `isi < 0.1, presence > 0.9`. The ISI value
    was 5x too strict, which would reject a large fraction of real units and
    make our passing fractions non-comparable with the paper's Fig 12.
    """
    import re

    from compbench.metrics import sorting

    doc = (sorting.__doc__ or "") + (sorting.qc_pass_fraction.__doc__ or "")
    # Whitespace-insensitive: the docstring aligns the operators in a block.
    flat = re.sub(r"\s+", " ", doc)
    # The active threshold block must state the driver's values...
    assert "isi_violations_ratio < 0.5" in flat
    assert "presence_ratio > 0.95" in flat
    # ...and the superseded value may appear ONLY as a documented
    # correction, never as a live threshold. Deleting the note would lose
    # the reason; asserting its absence outright would force that.
    for wrong in ("isi_violations_ratio < 0.1",):
        if wrong in flat:
            idx = flat.index(wrong)
            context = flat[max(0, idx - 200) : idx + 200]
            assert "earlier revision" in context, (
                f"{wrong!r} appears outside a correction note: {context!r}"
            )


@pytest.mark.ai_generated
def test_run_to_run_floor_is_part_of_the_contract() -> None:
    """The sorter is not deterministic; without a measured floor an
    agreement drop cannot be attributed to the codec."""
    from compbench.metrics import sorting

    assert hasattr(sorting, "run_to_run_floor")
    assert "run_to_run_floor" in sorting.__all__
