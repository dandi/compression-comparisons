"""Spike-sorting fidelity metrics — reflects Buccino et al. 2023 §3.2.2 exactly.

Two evaluation modes:

1. **Against ground truth (simulated / MEArec data):** compute per-unit
   accuracy / precision / recall via `SortingExtractor` ↔
   `GroundTruthComparison`. Report distributions, unit-count classifications
   (well-detected / false-positive / redundant / overmerged).

2. **Against lossless baseline (experimental data):** sort both the
   lossless-decoded output and the lossy-decoded output; compare via
   `SymmetricSortingComparison`; report per-unit spike-time agreement
   fraction. Also apply the Siegle et al. 2021 automatic curation
   (ISI-violations < 0.1, presence-ratio > 0.9, amplitude-cutoff < 0.1) and
   report passing/failing unit fractions.

These metric functions do NOT run the sorter themselves — they consume
`SortingExtractor` objects produced upstream by the sorting-eval pipeline
(see plan §4.7). This keeps the metric layer independent of the sorter
version + GPU availability.

Skeleton: full implementations land in Phase 3.5 [R1-H3]; the shapes below
define the contract downstream code can rely on.
"""

from __future__ import annotations

from typing import Any


def gt_comparison_metrics(
    ground_truth: Any,  # spikeinterface SortingExtractor
    candidate: Any,  # spikeinterface SortingExtractor
    exhaustive_gt: bool = True,
    delta_time_ms: float = 0.4,
    match_score: float = 0.5,
) -> dict[str, Any]:
    """Per-GT-unit accuracy / precision / recall (paper §3.2.2 Fig 10).

    Uses `spikeinterface.comparison.GroundTruthComparison`. On simulated
    MEArec data the paper reports distributions across all 100 GT units;
    we return per-unit metrics + summary statistics (mean, std, min, max,
    median) so a downstream aggregator can produce distribution plots.

    Args:
        ground_truth: SortingExtractor with true spike times/labels (from
            `compbench.datasets.mearec.load_ground_truth()`).
        candidate: SortingExtractor from Kilosort on the lossy-decoded traces.
        exhaustive_gt: True for MEArec — every candidate spike SHOULD match
            a GT spike. False for experimental data.
        delta_time_ms: spike-time tolerance for a match (paper: unspecified;
            SpikeInterface default 0.4 ms).
        match_score: minimum accuracy for a unit to count as "matched".

    Returns:
        {
          "n_gt_units": int,
          "n_candidate_units": int,
          "per_unit": [{"gt_unit_id": ..., "accuracy": ..., "precision": ..., "recall": ...}, ...],
          "accuracy_mean": float, "accuracy_std": float, "accuracy_median": float,
          "precision_mean": float, ..., "recall_mean": float, ...,
          "unit_counts": {"well_detected": int, "false_positive": int,
                          "redundant": int, "overmerged": int},
        }
    """
    raise NotImplementedError("Phase 3.5 R1-H3 — implementation pending")


def sorting_agreement(
    baseline: Any,  # SortingExtractor from lossless-decoded traces
    candidate: Any,  # SortingExtractor from lossy-decoded traces
    delta_time_ms: float = 0.4,
) -> dict[str, Any]:
    """Spike-time agreement between two sortings (paper §3.2.2 Fig 13).

    Uses `spikeinterface.comparison.SymmetricSortingComparison`. Match
    candidate units to baseline units; per matched pair report the fraction
    of spike times that are identical (within `delta_time_ms`). Also compute
    the "excess spike" distribution (paper Fig 13 lower panel): for each
    unit, `(candidate_n_spikes - baseline_n_spikes) / baseline_n_spikes`.
    Paper claim: distribution is symmetric around 0 for well-behaved lossy
    → no systematic bias.

    Returns:
        {
          "n_baseline_units": int, "n_candidate_units": int, "n_matched": int,
          "per_unit_agreement": [float, ...],   # one per matched pair
          "agreement_mean": float, "agreement_std": float, "agreement_median": float,
          "excess_spike_fraction": [float, ...],
          "excess_spike_symmetric": bool,       # |mean/std| < 0.1
        }
    """
    raise NotImplementedError("Phase 3.5 R1-H3 — implementation pending")


def unit_classification(
    sorting: Any,  # SortingExtractor, curated or not
    recording: Any | None = None,  # RecordingExtractor for waveform metrics
    quality_thresholds: dict[str, float] | None = None,
) -> dict[str, int]:
    """Paper §3.2.2 Fig 11 / Fig 12 unit-type counts.

    - **well_detected**: passing curation AND matched to a GT/baseline unit
    - **false_positive**: passing curation but NOT matched
    - **redundant**: matched but >95 % spike overlap with another candidate
    - **overmerged**: single candidate matches >1 GT/baseline unit

    Default `quality_thresholds` follow Siegle et al. 2021 (paper §2.3.2):
        isi_violations_ratio < 0.1
        presence_ratio > 0.9
        amplitude_cutoff < 0.1

    Available in `spikeinterface.qualitymetrics.compute_quality_metrics`.
    """
    raise NotImplementedError("Phase 3.5 R1-H3 — implementation pending")


def qc_pass_fraction(
    sorting: Any,
    recording: Any,
    quality_thresholds: dict[str, float] | None = None,
) -> dict[str, float | int]:
    """Fraction of units passing all three Siegle-2021 QC criteria.

    Paper Fig 12: "fractions of passing and failing units, instead, appear
    generally constant" for WavPack Hybrid across the bps sweep. The
    single-number "passing fraction" is the go/no-go summary for
    experimental data (where GT is unavailable).

    Returns: {n_units, n_passing, n_failing, passing_fraction, thresholds: {…}}
    """
    raise NotImplementedError("Phase 3.5 R1-H3 — implementation pending")


def waveform_feature_errors(
    baseline_analyzer: Any,  # spikeinterface SortingAnalyzer on lossless data
    candidate_analyzer: Any,  # on lossy-decoded data
    peripheral_um: float = 60.0,
) -> dict[str, Any]:
    """Waveform-feature relative errors (paper §3.2.3 Fig 14).

    Three features per matched unit:
    - peak-to-valley duration
    - full-width half-maximum
    - peak-to-trough ratio

    Evaluated on: (a) main channel of each unit, (b) peripheral channels at
    `peripheral_um` distance (paper: 60 µm). Reports relative error
    `|baseline - candidate| / baseline` per unit per feature.

    Paper target: < 10 % relative error for WavPack Hybrid across all bps.
    """
    raise NotImplementedError("Phase 3.5 R1-H3 — implementation pending")


__all__ = [
    "gt_comparison_metrics",
    "qc_pass_fraction",
    "sorting_agreement",
    "unit_classification",
    "waveform_feature_errors",
]
