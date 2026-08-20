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
   (ISI-violations-ratio < 0.5, presence-ratio > 0.95, amplitude-cutoff < 0.1) and
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
    lossless: Any,  # SortingExtractor from the lossless reconstruction
    candidate: Any,  # SortingExtractor from the lossy reconstruction
    match_score: float = 0.9,
    delta_time_ms: float = 0.4,
) -> dict[str, Any]:
    """Ordered spike-train agreement vs the lossless sort (paper Fig 13).

    The paper's operation, exactly (`benchmark-lossy-exp.py`):

        cmp = compare_multiple_sorters([lossless, tested], match_score=0.9)
        agreement = np.diag(cmp.get_ordered_agreement_scores())

    Three details that were wrong in the previous contract here:

    * It is `compare_multiple_sorters`, not `SymmetricSortingComparison`.
    * `match_score` is **0.9**, not the 0.5 default. That decides which
      units count as matched at all and shifts the whole curve.
    * The paper reports the **ordered curve** — a per-unit vector, sorted
      descending — because its shape against the noise floor is the claim.
      Reducing it to a mean is exactly the summarisation that hides the
      failure mode (see `gt_comparison_metrics`).

    Compute both variants the paper computes: on curated sortings (Fig 13)
    and on raw ones (Fig S8a/c).

    **This is only interpretable against a measured noise floor.** Kilosort
    is not deterministic: two runs on identical lossless data do not agree
    perfectly, and the paper draws that two-run curve as the reference line
    on every agreement figure. See `run_to_run_floor`.

    Returns:
        {
          "n_lossless_units": int, "n_candidate_units": int,
          "ordered_agreement": [float, ...],   # the curve, descending
          "n_matched_at_2": int,               # get_agreement_sorting(minimum_agreement_count=2)
          "match_score": float, "delta_time_ms": float,
        }
    """
    raise NotImplementedError("Phase 3.5 R1-H3 — implementation pending")


def run_to_run_floor(
    sortings: list[Any],  # >= 2 SortingExtractors from the SAME lossless data
    match_score: float = 0.9,
) -> dict[str, Any]:
    """The sorter's own noise floor — the reference every lossy curve needs.

    Buccino et al. §3.2.2: *"Even for two separate spike sorting runs
    applied to the same lossless data ... the detected spike trains do not
    match perfectly ... attributed to the inherent run-by-run variability
    for Kilosort 2.5."* Their driver builds it by comparing one strategy's
    lossless sorting against the other strategy's lossless sorting.

    Without this, an agreement drop at a given codec setting cannot be
    attributed: it may be the codec or it may be the sorter. Kilosort 4
    seeds explicitly (`np.random.seed(1)`, `torch.manual_seed(1)`) so its
    floor is expected to be higher than KS2.5's — which is a reason to
    measure it, not to assume it.

    Returns the same shape as `sorting_agreement` so the floor can be
    plotted on the same axes.
    """
    raise NotImplementedError("Phase 3.5 R1-H3 — implementation pending")


def excess_spikes(
    lossless: Any,
    candidate: Any,
    min_agreement: float = 0.5,
    delta_frames_multiplier: int = 2,
) -> dict[str, Any]:
    """Per-spike excess decomposition (paper Fig S8b/d).

    For unit pairs matched at >= `min_agreement`, the paper compares spike
    trains directly and splits the mismatch into two one-sided percentages:

        l1, l2 = compare_spike_trains(st1, st2, delta_frames=2*cmp.delta_frames)
        n_total = len(st1) + len(st2) - (l1 == "TP").sum()
        excess_lossless  = (l1 == "FN").sum() / n_total * 100
        excess_candidate = (l2 == "FP").sum() / n_total * 100

    and plots them as a two-sided histogram whose **symmetry** is the
    claim: no systematic gain or loss of spikes.

    The previous contract computed a *net count difference*
    `(cand_n - base_n) / base_n`, which is strictly weaker — a unit that
    gains 500 spikes and loses 500 reads as zero excess. It also invented
    an `excess_spike_symmetric` boolean (`|mean/std| < 0.1`) that appears
    nowhere in the paper.
    """
    raise NotImplementedError("Phase 3.5 R1-H3 — implementation pending")


def unit_classification(
    comparison: Any,  # spikeinterface GroundTruthComparison
) -> dict[str, int]:
    """Paper Fig 11 unit-type counts — thin wrapper over SpikeInterface.

    Delegates to `comparison.count_units_categories()`. The definitions are
    SpikeInterface's, and the previous contract here invented four different
    ones (it made curation part of the definition and described `redundant`
    as ">95 % spike overlap"). For the record, from
    `spikeinterface.comparison.paircomparisons`, all at default thresholds:

    * **well_detected** — Hungarian-matched with agreement >= 0.8.
    * **false_positive** — unmatched, and best-match agreement < 0.2.
      Requires `exhaustive_gt=True`.
    * **redundant** — unmatched, has a best-match GT unit for which it is
      not that unit's best match, agreement >= 0.2. "GT units detected
      twice or more."
    * **overmerged** — agreement > 0.2 against **two or more** GT units.

    Curation is a separate step and is not part of any of these. Record
    `well_detected_score` / `redundant_score` / `overmerged_score` /
    `chance_score` / `match_mode` in provenance — they are defaults, but a
    number is not interpretable without them.

    `num_false_positive` is the endpoint that actually moves: on the
    paper's own data it goes 52 -> 1435 between bit-truncation 4 and 5,
    while mean accuracy barely shifts.
    """
    raise NotImplementedError("Phase 3.5 R1-H3 — implementation pending")


def qc_pass_fraction(
    sorting: Any,
    recording: Any,
    quality_thresholds: dict[str, float] | None = None,
) -> dict[str, float | int]:
    """Units passing the paper's automatic curation (Fig 12).

    Thresholds, from the paper's driver `benchmark-lossy-exp.py` — which is
    authoritative because it produced the published counts::

        isi_violations_ratio < 0.5
        amplitude_cutoff     < 0.1
        presence_ratio       > 0.95

    Two traps here. The paper's own README states ``presence_ratio > 0.9``,
    contradicting its script; the script wins. And an earlier revision of
    this file recorded ``isi_violations_ratio < 0.1`` — 5x too strict,
    which would reject a large fraction of real units and make our passing
    fractions non-comparable with Fig 12.

    Metric names are SpikeInterface's
    (``["isi_violation", "presence_ratio", "amplitude_cutoff"]`` requested;
    columns come back as ``isi_violations_ratio`` / ``presence_ratio`` /
    ``amplitude_cutoff``). ``amplitude_cutoff`` needs spike amplitudes
    computed first. Pin the names and the SpikeInterface version — the
    paper ran 0.97.1 and left its ``qm_params`` dict unused, so its numbers
    reflect that version's defaults.

    **Fig 12 is normalised, and not the way the name suggests.** The paper
    plots each session's passing/failing counts divided by *that session's
    own factor-0 (lossless) counts*, not by its unit total. A raw
    ``n_passing / n_units`` is a different quantity and will not overlay.

    Requires the full recording: ``presence_ratio`` bins at 60 s, so a
    100 s slice leaves a single bin and the metric degenerates to ~1 for
    every unit.

    Returns: {n_units, n_passing, n_failing, passing_fraction,
              passing_fraction_vs_lossless, thresholds: {...}}
    """
    raise NotImplementedError("Phase 3.5 R1-H3 — implementation pending")


def waveform_feature_errors(
    gt_sorting: Any,  # MEArec ground-truth SortingExtractor
    reference_recording: Any,  # the ORIGINAL band-passed recording
    candidate_recording: Any,  # the lossy-decoded, band-passed recording
    distances_um: tuple[float, ...] = (0.0, 30.0, 60.0, 90.0),
    ms_after: float = 5.0,
    upsampling_factor: int = 10,
    seed: int = 2308,
) -> dict[str, Any]:
    """Waveform-feature relative errors (paper Fig 14).

    **No sorter is involved.** The paper applies the *ground-truth* spike
    trains to both the original and the lossy recording, so the units are
    identical by construction and the measurement is free of sorter
    variability. The previous contract here took two `SortingAnalyzer`s
    and matched units between two *sortings*, which injects exactly the
    variance the paper designed out — pure loss of power, no benefit.

    Channels come from a `ChannelSparsity` built on the GT extremum
    channel plus the nearest channels at each of `distances_um`
    (paper: 0 / 30 / 60 / 90 um; Fig 14 plots 0 and 60).

    Features are SpikeInterface `compute_template_metrics` names — three
    are plotted: `peak_to_valley`, `half_width`, `peak_trough_ratio`.
    (Note `half_width`, not "full-width half-maximum" as previously
    written here; the paper's prose says FWHM but its code computes
    SpikeInterface's `half_width`.) `repolarization_slope` and
    `recovery_slope` are computed by the paper but not plotted.

    Error is `|metric_lossy - metric_reference| / |metric_reference|`,
    where the reference template comes from the **uncompressed** recording.

    This carries the paper's only stated numeric tolerance: all error
    distributions **below 10 %** for WavPack Hybrid, against "well above
    20 %" for the bit-truncation settings it rejects.
    """
    raise NotImplementedError("Phase 3.5 R1-H3 — implementation pending")


__all__ = [
    "excess_spikes",
    "gt_comparison_metrics",
    "qc_pass_fraction",
    "run_to_run_floor",
    "sorting_agreement",
    "unit_classification",
    "waveform_feature_errors",
]
