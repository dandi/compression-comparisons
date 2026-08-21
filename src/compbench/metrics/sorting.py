"""Spike-sorting fidelity metrics — reflects Buccino et al. 2023 §3.2.2 exactly.

Two evaluation modes:

1. **Against ground truth (simulated / MEArec data):** compute per-unit
   accuracy / precision / recall via `SortingExtractor` ↔
   `GroundTruthComparison`. Report distributions, unit-count classifications
   (well-detected / false-positive / redundant / overmerged).

2. **Against lossless baseline (experimental data):** sort both the
   lossless-decoded output and the lossy-decoded output; compare via
   `compare_multiple_sorters(..., match_score=0.9)` and take the diagonal
   of the ordered agreement matrix. (NOT `SymmetricSortingComparison` —
   that was wrong here even after the function below was corrected.) Also apply the Siegle et al. 2021 automatic curation
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
    ground_truth: Any,  # spikeinterface SortingExtractor (MEArec ground truth)
    candidate: Any,  # spikeinterface SortingExtractor (sorted lossy traces)
    exhaustive_gt: bool = True,
    delta_time_ms: float = 0.4,
    match_score: float = 0.5,
    well_detected_score: float = 0.8,
    redundant_score: float = 0.2,
    overmerged_score: float = 0.2,
    chance_score: float = 0.1,
) -> dict[str, Any]:
    """Ground-truth comparison — paper Figs 10 and 11.

    Thin, deliberate wrapper over
    `spikeinterface.comparison.compare_sorter_to_ground_truth`. Every
    threshold is a SpikeInterface default, but each is passed explicitly
    and echoed back in the result: a unit count is not interpretable
    without the scores that produced it, and defaults change between
    versions.

    Returns both the pooled averages (the paper's Fig-10 quantity) and the
    **per-unit** table. The paper only published the pooled scalar, but
    keeping the 100-unit distribution is what lets us answer *which* units
    broke rather than "the mean moved 0.2 %" — and the paper's own Fig 11
    is the demonstration that a pooled mean hides the failure: at NP1
    bit-truncation 5 the mean accuracy is "only slightly affected" while
    false positives go 65 -> 1435 (52 at lossless).

    Verified against the authors' released sortings: all 32 simulated cells
    reproduce `benchmark-lossy-sim.csv` exactly under SpikeInterface
    0.104.8, including that 65 -> 1435 transition.
    """
    import spikeinterface.comparison as sc

    cmp = sc.compare_sorter_to_ground_truth(
        ground_truth,
        candidate,
        exhaustive_gt=exhaustive_gt,
        delta_time=delta_time_ms,
        match_score=match_score,
        well_detected_score=well_detected_score,
        redundant_score=redundant_score,
        overmerged_score=overmerged_score,
        chance_score=chance_score,
    )
    pooled = cmp.get_performance(method="pooled_with_average", output="dict")
    per_unit = cmp.get_performance(method="by_unit")
    counts = {str(k): int(v) for k, v in cmp.count_units_categories().items()}

    return {
        "pooled": {k: float(v) for k, v in pooled.items()},
        "per_unit": per_unit.reset_index().to_dict(orient="records"),
        "unit_counts": counts,
        "n_gt_units": len(ground_truth.unit_ids),
        "n_candidate_units": len(candidate.unit_ids),
        # Echoed so a count is never read without the scores behind it.
        "comparison_params": {
            "exhaustive_gt": exhaustive_gt,
            "delta_time_ms": delta_time_ms,
            "match_score": match_score,
            "well_detected_score": well_detected_score,
            "redundant_score": redundant_score,
            "overmerged_score": overmerged_score,
            "chance_score": chance_score,
            "match_mode": "hungarian",
        },
    }


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

    **This is only interpretable against a measured noise floor** — on
    EXPERIMENTAL data. See `run_to_run_floor` for the scope: the paper's
    nondeterminism finding is about its experimental sessions, and its own
    simulated sortings turn out to be bit-identical between runs.

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
    for Kilosort 2.5."*

    **Scope, measured against the paper's own released sortings.** That
    statement holds for EXPERIMENTAL data — on CSHZAD026 the factor-0
    curated curve has median 0.9716 with only 68 % of units at or above
    0.9. It does NOT hold for their simulated data: the NP1 and NP2
    `bit_truncation-0` vs `wavpack-0` sortings are **bit-identical**, so
    the MEArec floor is exactly 1.0. (The mean ordered agreement reads
    0.9937 / 0.9803 only because a few sorter units are empty — the sim
    driver never calls `remove_empty_units`.)

    So the floor must be *measured*, not assumed in either direction: do
    not assume it is 1.0 on experimental data, and do not assume it is
    below 1.0 on simulated data.

    Construction: the paper's floor is not two runs of one config. It is
    strategy A at factor 0 versus strategy B at factor 0 — two different
    lossless codecs, one sorter run each.

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
    paper's own data it goes 65 -> 1435 between bit-truncation 4 and 5 (52
    at lossless) -- a 22x rise -- while mean accuracy falls only 7 %.
    """
    counts = comparison.count_units_categories()
    return {str(k): int(v) for k, v in counts.items()}


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

    **Metric names changed between SpikeInterface versions**, and one of
    the three changed meaning. The paper ran SI 0.97.1; we have 0.104.8:

    ===================  ==========================  ==================
    paper (0.97.1)       modern (0.104.8)            equivalent?
    ===================  ==========================  ==================
    peak_to_valley       peak_to_trough_duration     yes (exact)
    peak_trough_ratio    peak_after_to_trough_ratio  yes (up to sign)
    half_width           trough_half_width           **NO**
    ===================  ==========================  ==================

    0.97.1's `get_half_width` takes the *outermost* half-amplitude
    crossings across the whole window; 0.104's takes the crossings adjacent
    to the trough. Measured over the paper's own 400 NP1 (unit x channel)
    templates the p90 relative difference is **57 %** — five times the 10 %
    line Fig 14 is judged against. Compute both, report which, and never
    overlay the 0.104 definition on Fig 14.

    `repolarization_slope` and `recovery_slope` are computed by the paper
    but not plotted.

    `ms_before` is **3.0**, not the modern default of 1.0 — the paper never
    overrode SI 0.97.1's default, and its vendored
    `waveforms/params.json` confirms it. At the modern default the template
    window is half as long and the features differ silently.

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
