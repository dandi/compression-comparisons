"""Spike-sorting fidelity metrics — reflects Buccino et al. 2023 §3.2.2 exactly.

**What this module is, and what it is not.** These functions consume spike
trains. They do not produce them, and they do not compress anything. The
experiment they serve runs like this:

    raw traces (int16, ground truth known)
      -> LSB correction
      -> LOSSY compress          (bittrunc-N / wavpack-hybrid bps / T.261 QP)
      -> decompress
      -> CR, RMSE, band-limited RMSE, PRDN        [signal-level metrics]
      -> band-pass
      -> RUN THE SORTER ON THE DECOMPRESSED TRACES
      -> compare that sorting against ground truth        [this module]

The whole point is the effect of *lossy* compression on the spikes you get
out. Lossless cells are the anchor — the reference the lossy arms are
measured against, and a null check that a lossless codec changes nothing —
not a result in themselves.

Nothing here compresses a sorting. What gets compressed is always the raw
traces.

Two evaluation modes:

1. **Against ground truth (simulated / MEArec data):** compute per-unit
   accuracy / precision / recall via `SortingExtractor` <->
   `GroundTruthComparison`. Report distributions, unit-count classifications
   (well-detected / false-positive / redundant / overmerged).

2. **Against lossless baseline (experimental data):** sort both the
   lossless-decoded output and the lossy-decoded output; compare via
   `compare_multiple_sorters(..., match_score=0.9)` and take the diagonal
   of the ordered agreement matrix. (NOT `SymmetricSortingComparison` --
   that was wrong here even after the function below was corrected.)

   Also apply the Siegle et al. 2021 automatic curation
   (ISI-violations-ratio < 0.5, presence-ratio > 0.95, amplitude-cutoff < 0.1) and
   report passing/failing unit fractions.

These metric functions do NOT run the sorter themselves — they consume
`SortingExtractor` objects produced upstream by the sorting-eval pipeline
(see plan §4.6a). That keeps the metric layer independent of the sorter
version and GPU availability, and it is why the two implemented functions
could be verified against the authors' released sortings before any of the
pipeline existed. It is emphatically NOT a claim that the experiment needs
no sorter.

Status: `gt_comparison_metrics` and `unit_classification` are implemented
and verified; the rest are contract-only skeletons, and the pipeline that
would feed them (compress -> decompress -> sort) is not built yet.
"""

from __future__ import annotations

import itertools
import pathlib
import shutil
from typing import Any

import numpy as np


def _analyzer_on_disk(sorting, recording, sparse=False):
    """Build a SortingAnalyzer that does not allocate in /dev/shm.

    SpikeInterface's default (and its "memory" format) puts waveform buffers
    in POSIX shared memory. Containers routinely ship a 64 MB /dev/shm, where
    the allocation succeeds and the first touch past the limit raises SIGBUS
    -- the process dies with exit 135, no traceback, no Python exception to
    catch. Writing to a temp folder trades a little I/O for not depending on
    the host's shm sizing at all.

    The caller owns the returned folder's lifetime via `analyzer.folder`.
    """
    import tempfile

    from spikeinterface import create_sorting_analyzer

    tmpdir = tempfile.mkdtemp(prefix="compbench-analyzer-")
    return create_sorting_analyzer(
        sorting,
        recording,
        sparse=sparse,
        format="binary_folder",
        folder=str(pathlib.Path(tmpdir) / "analyzer"),
    )


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
    from spikeinterface.comparison import compare_multiple_sorters

    cmp = compare_multiple_sorters(
        [lossless, candidate],
        name_list=["lossless", "candidate"],
        match_score=match_score,
        delta_time=delta_time_ms,
    )
    # the paper takes the DIAGONAL of the ordered agreement matrix: unit i of
    # the lossless sort against its own best match in the candidate, sorted
    # descending. The curve's shape against the floor is the claim, so the
    # vector is returned whole and never averaged here.
    ordered = np.diag(np.asarray(cmp.get_ordered_agreement_scores()))
    agreement_sorting = cmp.get_agreement_sorting(minimum_agreement_count=2)
    return {
        "n_lossless_units": int(len(lossless.unit_ids)),
        "n_candidate_units": int(len(candidate.unit_ids)),
        "ordered_agreement": [float(x) for x in ordered],
        "n_matched_at_2": int(len(agreement_sorting.unit_ids)),
        "match_score": float(match_score),
        "delta_time_ms": float(delta_time_ms),
    }


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
    if len(sortings) < 2:
        raise ValueError(
            "a run-to-run floor needs at least two sortings of the same "
            f"lossless data; got {len(sortings)}"
        )
    # Same shape as sorting_agreement() so the floor plots on the same axes.
    # Pairwise over every combination, then the ELEMENTWISE MINIMUM across
    # pairs: the floor is the worst agreement the sorter produces on
    # identical input, not the average of its better days.
    curves = []
    for a, b in itertools.combinations(range(len(sortings)), 2):
        curves.append(
            sorting_agreement(sortings[a], sortings[b], match_score=match_score)[
                "ordered_agreement"
            ]
        )
    n = min(len(c) for c in curves)
    floor = [float(min(c[i] for c in curves)) for i in range(n)]
    return {
        "n_lossless_units": int(len(sortings[0].unit_ids)),
        "n_candidate_units": int(len(sortings[-1].unit_ids)),
        "ordered_agreement": floor,
        "n_matched_at_2": int(min(len(s_.unit_ids) for s_ in sortings)),
        "match_score": float(match_score),
        "delta_time_ms": 0.4,
        "n_pairs": len(curves),
        "per_pair_ordered_agreement": [[float(x) for x in c] for c in curves],
        # a floor of exactly 1.0 is a real and expected outcome on simulated
        # data (the paper's own MEArec sortings are bit-identical); it is NOT
        # evidence that the measurement failed
        "is_perfect": bool(floor and min(floor) == 1.0),
    }


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
    from spikeinterface.comparison import compare_two_sorters
    from spikeinterface.comparison.comparisontools import compare_spike_trains

    cmp = compare_two_sorters(
        lossless, candidate, sorting1_name="lossless", sorting2_name="candidate"
    )
    fs = float(lossless.get_sampling_frequency())
    delta_frames = int(delta_frames_multiplier * cmp.delta_frames)

    rows = []
    for unit1 in lossless.unit_ids:
        unit2 = cmp.get_best_unit_match1(unit1)
        if unit2 is None or (hasattr(unit2, "__len__") and len(str(unit2)) == 0):
            continue
        score = float(cmp.get_agreement_fraction(unit1, unit2))
        if score < min_agreement:
            continue
        st1 = lossless.get_unit_spike_train(unit1)
        st2 = candidate.get_unit_spike_train(unit2)
        if len(st1) == 0 and len(st2) == 0:
            continue
        l1, l2 = compare_spike_trains(st1, st2, delta_frames=delta_frames)
        l1 = np.asarray(l1)
        l2 = np.asarray(l2)
        n_tp = int((l1 == "TP").sum())
        n_total = len(st1) + len(st2) - n_tp
        if n_total <= 0:
            continue
        rows.append(
            {
                "unit_lossless": str(unit1),
                "unit_candidate": str(unit2),
                "agreement": score,
                "n_spikes_lossless": int(len(st1)),
                "n_spikes_candidate": int(len(st2)),
                # two ONE-SIDED percentages; their symmetry is the claim. A
                # net difference would read zero for a unit that gains 500
                # spikes and loses 500.
                "excess_lossless_percent": float((l1 == "FN").sum() / n_total * 100),
                "excess_candidate_percent": float((l2 == "FP").sum() / n_total * 100),
            }
        )

    lo = [r["excess_lossless_percent"] for r in rows]
    hi = [r["excess_candidate_percent"] for r in rows]
    return {
        "n_matched_units": len(rows),
        "min_agreement": float(min_agreement),
        "delta_frames": delta_frames,
        "sampling_frequency_hz": fs,
        "per_unit": rows,
        "excess_lossless_percent_median": float(np.median(lo)) if lo else None,
        "excess_candidate_percent_median": float(np.median(hi)) if hi else None,
    }


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
    n_passing_lossless: int | None = None,
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
    from spikeinterface.metrics import compute_quality_metrics

    analyzer = _analyzer_on_disk(sorting, recording, sparse=True)
    # amplitude_cutoff needs spike amplitudes, which need templates
    analyzer.compute(["random_spikes", "waveforms", "templates", "spike_amplitudes"])

    thresholds = {
        # Siegle et al. 2021, as the paper's SCRIPT applies them. Its README
        # says presence_ratio > 0.9; the script wins. An earlier revision of
        # this file had isi_violations_ratio < 0.1, 5x too strict.
        "isi_violations_ratio": 0.5,
        "amplitude_cutoff": 0.1,
        "presence_ratio": 0.95,
    }
    if quality_thresholds:
        thresholds.update(quality_thresholds)
    qm = compute_quality_metrics(
        analyzer,
        metric_names=["isi_violation", "presence_ratio", "amplitude_cutoff"],
    )
    missing = [c for c in thresholds if c not in qm.columns]
    if missing:
        raise RuntimeError(
            f"quality metrics missing column(s) {missing}; got {list(qm.columns)}. "
            "Metric column names drift between SpikeInterface versions -- pin "
            "the version rather than renaming silently."
        )
    passing = (
        (qm["isi_violations_ratio"] < thresholds["isi_violations_ratio"])
        & (qm["amplitude_cutoff"] < thresholds["amplitude_cutoff"])
        & (qm["presence_ratio"] > thresholds["presence_ratio"])
    )
    n_units = int(len(qm))
    n_passing = int(passing.sum())
    out = {
        "n_units": n_units,
        "n_passing": n_passing,
        "n_failing": n_units - n_passing,
        "passing_fraction": (n_passing / n_units) if n_units else None,
        "thresholds": thresholds,
        "passing_unit_ids": [str(u) for u in qm.index[passing]],
    }
    # Fig 12 normalises by the session's OWN lossless counts, not by the unit
    # total. `passing_fraction` is a different quantity and will not overlay.
    if n_passing_lossless is not None:
        out["passing_fraction_vs_lossless"] = (
            n_passing / n_passing_lossless if n_passing_lossless else None
        )
    else:
        out["passing_fraction_vs_lossless"] = None
    return out


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
    def _templates(recording):
        analyzer = _analyzer_on_disk(gt_sorting, recording, sparse=False)
        analyzer.compute(
            {
                "random_spikes": {"max_spikes_per_unit": 500, "seed": seed},
                # ms_before is 3.0, NOT the modern default of 1.0: the paper
                # never overrode SI 0.97.1's default and its vendored
                # waveforms/params.json confirms it. At 1.0 the window is half
                # as long and every feature shifts silently.
                "waveforms": {"ms_before": 3.0, "ms_after": ms_after},
                "templates": {"ms_before": 3.0, "ms_after": ms_after},
            }
        )
        ext = analyzer.get_extension("templates")
        data = np.asarray(ext.get_data())
        folder = getattr(analyzer, "folder", None)
        return folder, data

    ref_folder, ref_templates = _templates(reference_recording)
    cand_folder, cand_templates = _templates(candidate_recording)
    for _f in (ref_folder, cand_folder):
        if _f is not None:
            shutil.rmtree(pathlib.Path(_f).parent, ignore_errors=True)
    if ref_templates.shape != cand_templates.shape:
        raise RuntimeError(
            f"template shape mismatch {ref_templates.shape} vs "
            f"{cand_templates.shape}: the two recordings must share geometry "
            "and the same ground-truth spike trains"
        )

    fs = float(reference_recording.get_sampling_frequency())
    locs = reference_recording.get_channel_locations()

    def _upsample(wf):
        """Interpolate `upsampling_factor`x before measuring.

        peak_to_valley and half_width are derived from sample INDICES, so at
        32 kHz they are quantised to ~1/N of the feature width -- a
        one-sample shift on a ten-sample half-width reads as exactly 10 %,
        which is the paper's whole tolerance. The paper upsamples for this
        reason; without it these two features are step functions and the
        Fig 14 comparison is meaningless.
        """
        if upsampling_factor <= 1:
            return wf, fs
        x = np.arange(wf.size, dtype=float)
        xi = np.linspace(0.0, wf.size - 1.0, wf.size * upsampling_factor)
        return np.interp(xi, x, wf), fs * upsampling_factor

    def _features(wf):
        """The paper's (SI 0.97.1) definitions, implemented directly.

        SI 0.104 renamed these and CHANGED half_width: 0.97.1 takes the
        OUTERMOST half-amplitude crossings across the window, 0.104 takes the
        ones adjacent to the trough. Over the paper's own NP1 templates the
        p90 relative difference is 57 %, five times the 10 % line Fig 14 is
        judged against -- so relying on whatever the installed version calls
        `half_width` would silently invalidate the comparison.
        """
        wf, eff_fs = _upsample(np.asarray(wf, dtype=float))
        trough_i = int(np.argmin(wf))
        trough = float(wf[trough_i])
        if trough >= 0:
            return None
        after = wf[trough_i:]
        peak_rel = int(np.argmax(after))
        peak_i = trough_i + peak_rel
        peak = float(wf[peak_i])
        half = trough / 2.0
        below = np.flatnonzero(wf <= half)
        half_width = (
            float((below[-1] - below[0]) / eff_fs) if below.size >= 2 else float("nan")
        )
        return {
            "peak_to_valley": float((peak_i - trough_i) / eff_fs),
            "peak_trough_ratio": float(peak / trough) if trough else float("nan"),
            "half_width": half_width,
        }

    rows = []
    for u_idx, unit_id in enumerate(gt_sorting.unit_ids):
        extremum_ch = int(np.argmin(ref_templates[u_idx].min(axis=0)))
        origin = locs[extremum_ch]
        dists = np.linalg.norm(locs - origin, axis=1)
        for target_um in distances_um:
            ch = int(np.argmin(np.abs(dists - target_um)))
            ref_f = _features(ref_templates[u_idx][:, ch])
            cand_f = _features(cand_templates[u_idx][:, ch])
            if ref_f is None or cand_f is None:
                continue
            row = {
                "unit_id": str(unit_id),
                "distance_um": float(target_um),
                "channel_index": ch,
                "actual_distance_um": float(dists[ch]),
            }
            for name, ref_v in ref_f.items():
                cand_v = cand_f[name]
                row[f"{name}_reference"] = ref_v
                row[f"{name}_candidate"] = cand_v
                row[f"{name}_relative_error"] = (
                    float(abs(cand_v - ref_v) / abs(ref_v))
                    if ref_v not in (0.0,) and np.isfinite(ref_v) and np.isfinite(cand_v)
                    else float("nan")
                )
            rows.append(row)

    summary = {}
    for name in ("peak_to_valley", "peak_trough_ratio", "half_width"):
        for target_um in distances_um:
            vals = [
                r[f"{name}_relative_error"]
                for r in rows
                if r["distance_um"] == target_um
                and np.isfinite(r[f"{name}_relative_error"])
            ]
            if vals:
                summary[f"{name}@{target_um:g}um"] = {
                    "median_relative_error": float(np.median(vals)),
                    "p90_relative_error": float(np.percentile(vals, 90)),
                    "max_relative_error": float(np.max(vals)),
                    "n": len(vals),
                    # the paper's only stated tolerance: all distributions
                    # below 10 % for WavPack Hybrid, "well above 20 %" for the
                    # bit-truncation settings it rejects
                    "within_10_percent": bool(np.max(vals) < 0.10),
                }
    return {
        "metric_definition": "buccino2023/spikeinterface-0.97.1",
        "definition_note": (
            "half_width uses the OUTERMOST half-amplitude crossings, as in "
            "SI 0.97.1. Do not overlay SI >=0.104's trough-adjacent "
            "half_width on Fig 14."
        ),
        "ms_before": 3.0,
        "ms_after": float(ms_after),
        "upsampling_factor": int(upsampling_factor),
        "seed": int(seed),
        "n_units": int(len(gt_sorting.unit_ids)),
        "per_unit_channel": rows,
        "summary": summary,
    }


__all__ = [
    "excess_spikes",
    "gt_comparison_metrics",
    "qc_pass_fraction",
    "run_to_run_floor",
    "sorting_agreement",
    "unit_classification",
    "waveform_feature_errors",
]
