# T.261 profile design for microelectrode data — agreed plan

Synthesis of four independent reviews (codec internals, signal
characteristics, empirical results, experiment design), 2026-09-03. Where
the reviews disagreed, the disagreement and its resolution are recorded
rather than smoothed over.

## The situation

Every T.261 number in this study comes from **one** preset,
`combinedPresetEEG_IndepChannel`, varying only `StepSizeForQP`. That preset
was tuned for scalp EEG. Against our data the mismatch is ~100× on every
time constant and ~1000× on electrode spacing.

## Two verified findings that reframe the problem

**1. The preset actively disables the encoder's own lossy-mode adaptation.**
`EncAppCfg.cpp:70-84` auto-configures `LOG2_MAX_BLOCK_SIZE=8`,
`MAX_SPLIT_DEPTH=2`, `MaxAbsDeltaQP=1` at `StepSizeForQP >= 1.5`. The preset
pins **10 / 0 / 0**. So the entire QP 1.5-8.0 sweep ran with block splitting
off, blocks 4x larger than the encoder would choose, and per-block QP
adaptation off. Testing this costs nothing but deleting three lines.

**2. T.261's quantisation error is spectrally flat, and that is an
accident.** Measured in-band (300-6000 Hz) error power fraction: T.261
**0.29-0.35** against a white-noise expectation of 0.38; WavPack Hybrid
**0.39-0.67**. T.261 spends ~2/3 of its error budget where the sorter cannot
see it, which is why it carries lower waveform error than WavPack at matched
CR. It was not shaped on purpose, and **no frequency-weighting knob exists in
the reference software** (no `ScalingList`, `QuantWeight`, `freqWeight`).
Deliberate shaping therefore requires band splitting, not a parameter.

## Where the redundancy is — two reviews converged independently

| axis | spike band (300-6000 Hz) | LFP (<300 Hz) |
| ---- | -----------------------: | ------------: |
| temporal prediction gain | **4.2-4.7 bits** (AR8-16) | 6.4-7.9 bits @30 kHz |
| cross-channel gain | **0.14-0.67 bits** | **3.2-4.2 bits** |
| nearest-neighbour correlation | 0.50-0.61 | 0.75-0.96 |
| low-rank? | no (PC1 = 7-16 %) | yes (top-4 PCs = 55-94 %) |
| correlation length | 50-100 um | 250-500 um |

Confirmed empirically from the delta-filter sweep: temporal differencing is
worth **+18 %** to blosc-zstd and **+0.1 %** to WavPack (which already has a
temporal predictor); channel-axis differencing is consistently **negative**.

## The one substantive disagreement, and its resolution

Two reviews called `ChannelGroupSize` "the single largest unexplored axis".
A third argued cross-channel coding cannot pay in the spike band, with three
quantitative reasons, and the empirical review independently found spatial
differencing negative.

**Resolved: `ChannelGroupSize` is an LFP axis, not a spike axis.** The
reasons the spike case fails are specific and checkable:

* nearest-neighbour correlation of 0.50-0.61 caps the gain at ~0.3-0.7 bits
  against the ~10 uV independent noise floor;
* the signal is not low-rank, so joint coding has little structure to find;
* **the ADC multiplexes.** `inter_sample_shift` has 12 distinct values on
  NP1, spanning 0.92 samples. Neighbouring channels are not sampled at the
  same instant, so a same-time-index cross-channel predictor fights a
  fractional-sample skew — worst exactly at spike frequencies. Any
  cross-channel arm for spikes must first enable the sub-sample filters
  (`UseLMSigFiltering`), which the preset sets to 0.
* and it may be unaffordable: the joint-channel preset **timed out at 1800 s
  on a 10 s slice, twice**.

## Ranked hypotheses

Cost is per candidate. "Free" means no encoder-time increase.

| # | change | rationale | expected | cost |
| -: | ------ | --------- | -------- | ---- |
| **H1** | drop the `LOG2_MAX_BLOCK_SIZE` / `MAX_SPLIT_DEPTH` / `MaxAbsDeltaQP` pins; let auto-config run | the preset overrides the encoder's own lossy defaults | +2-8 % CR at equal distortion; possible FP reduction | free |
| **H2** | LSB-correct every Open Ephys input; test `cgps_allow_zero_lsb_flag=1` in the lossy preset | T.261 pays **3.43 bits/sample** for zero information and exploits the lattice least of all codecs tested | lossless CR 2.01 -> 3.53, already demonstrated | free |
| **H3** | `IntraPeriod` >= chunk length | 98304 samples = 3.28 s here vs 384 s at EEG rates; adaptive state is destroyed ~3x per 10 s chunk | unquantified; explains why chunk size 10 s vs 60 s changes nothing today | free |
| **H4** | `MAX_SPLIT_DEPTH=4..6` with `LOG2_MAX_BLOCK_SIZE=10`, `MaxAbsDeltaQP=1..3` | DCT gain saturates by N=64, but per-block **adaptivity** is worth +0.12 (AP) to +0.36 (wideband) bits | +0.10-0.15 bits/sample | encoder time |
| **H5** | band-split: code <300 and 300-6000 Hz as separate streams with independent QP | the only route to shaped error, given no weighting knob exists. 50 % of spike-discriminative energy is below 1 kHz, 80 % below 1.33 kHz | the big one: potentially 2-3x usable CR at fixed sorting fidelity | adapter work; changes the artifact |
| **H6** | `ChannelDistortionScaleFactor` 0.5, 1.0 | equalises error-to-noise across channels whose sigma spans 4.5x (IBL) to 20x (NP2); matches the sorter's per-channel k*MAD threshold | FP reduction at matched CR | needs seekable input; forces `max_abs_delta_qp_idx=7` |
| **H7** | decorrelate the error at fixed RMSE: `TrellisQuantDelay>0`, `PerceptMode 1-3`, `QuantMode 0` vs `2` | FP inflation tracks error *structure*, not magnitude; none swept | FP headroom for free | encoder time |
| **H8** | buy back compute: `BMNumCandsFullRD`, `LMNumCandsFullRD`, `UseMultHypPreSearch*` | lossy is **4.2x more expensive than lossless** (52.3x vs 12.5x realtime), so the cost is encoder search; distortion is already at the uniform-quantiser bound so search has little to protect | large speedup, small rate loss | free (negative) |
| **H9** | LFP profile: `ChannelGroupSize=0` or `AutoChannelGroup`, `LOG2_MAX_BLOCK_SIZE=11-13`, low `LMS_ORDER`, high `MaxAbsDeltaQP` | opposite prescription to spikes; cross-channel alone is worth 3.2-4.2 bits | substantial | joint-channel may be infeasible — verify cost first |
| **H10** | try the **ACoM** and **EMG** presets as-is | ACoM is the only family tuned on kHz-rate data and the only one enabling block splitting; EMG is spiky broadband | free reference points | free |

**Do not pursue**, on the evidence:

* **Raising `LMS_ORDER`.** AR16 = 4.72 bits vs AR32 = 4.74 — saturated.
* **T.261 lossless.** WavPack lossless matches its CR (3.595 vs 3.563) at
  **1/24 the encode cost and 1/14 the decode cost**.
* **QP < 5.** Below CR 7.16 WavPack Hybrid does the same job for ~1/72 the
  compute. T.261's only defensible territory is **CR > 7.16**, above
  WavPack's hard rate ceiling.

## Blocking work

`T261Adapter` — the class profiles actually reach — takes only `preset`,
`bit_depth`, `step_size_for_qp`, `max_abs_delta_qp`. `T261Codec` already
supports `extra_args` but the adapter does not forward it, so every
hypothesis above except H2/H10 raises `TypeError` before the encoder runs.

Three edits unlock the space: forward `**overrides` as `extra_args`, add a
`cfg_dir` parameter so candidate cfgs live in the tool repo (never patch the
`src/bwc/` subdataset), and record the cfg sha256 in `describe()` so
candidate identity is not a filename.

Two free wins in the same edit:

* **Suppress the `.rec` file.** `WRITE_ENC_REC=1` means every encode also
  writes a full reconstructed PCM file — **220 MB per 10 s chunk**, verified
  on disk, inside the timed region. `--BitstreamFile=-` suppresses it.
* **Skip the pre-analysis passes**, which re-read the input four times.
  Requires an explicit `--RerefMode=0`; verify a round-trip first.

## Staged search

Distortion is exactly `rmse = QP/sqrt(12)` (measured 0.91-1.06x across 30
lossy cells), so **distortion needs no measurement — only rate does.** That
collapses the search.

| rung | substrate | gate | budget |
| ---- | --------- | ---- | ------ |
| 0 | 10 s, 1 chunk | validity; re-encode byte-identical; **cost <= 1.5x stock**; projected chunk time <= timeout/4 | ~0.3 cell-h each |
| 1 | 60 s MEArec, 4 QP points | rate at matched distortion; per-channel PRDN max | ~3.5 cell-h each |
| 2 | second window + MEArec NP2 + one real LSB-corrected recording | rank stability across window and substrate | ~10 cell-h each |
| 3 | **600 s MEArec, sorting** | FP <= 126+17, well-detected >= 96-4, plus CR > stock at equal waveform p90 | ~19 cell-h + 3.5 h GPU each |
| 4 | real recordings, no ground truth | agreement against a lossless-baseline sorting | confirmation only |

Rungs 1-2 are **sorter-free by design**: short slices are *biased*, not
merely noisy — 6 of 10 arms reversed the sign of an endpoint between 100 s
and 600 s, and a biased proxy cannot be averaged out. Sorting is 600 s or it
is not evidence.

**Ranking uses rate at matched distortion; the waveform-feature p90 is the
acceptance gate, not the ranking metric.** Within T.261, band-limited RMSE
predicts FP inflation perfectly (Spearman +1.000, n=5) and the expensive
waveform metric predicts it *worse* (+0.600) — but p90 is the paper's
published criterion, so it decides pass/fail. Different jobs.

Carry **2 rejected candidates into rung 3 anyway.** Without them the staged
design cannot be falsified.

## The error budget, in the units that matter

Express the target as **error-to-noise ratio per channel**, never absolute
uV and never bps:

| error RMS / sigma_noise | outcome |
| ----------------------: | ------- |
| <= 0.15 | FP inflation under ~10 % |
| <= 0.33 | practical edge (+58 FP at QP 8.0) |
| 0.54-0.63 | **cliff** — well-detected collapses 100 -> 77 |

`step_size_for_qp` is an absolute step in ADC counts, so a fixed QP delivers
2.2x different relative quality across our recordings. Every cross-recording
T.261 comparison to date has been at unmatched quality. Solve for QP per
recording from the bandpassed per-channel MAD instead.

## Caveats that must travel with any result

* **MEArec is a favourable substrate for a lossy codec.** 45 % of its power
  is above 6 kHz against 5 % for real NP1, and it has no LFP, no drift, no
  bursting, and a 10-bit ADC. Every sorting-fidelity number in this study
  rests on it. CR-at-fidelity claims need real-data confirmation.
* **The lossless null control is weaker than previously stated.** Four
  lossless arms producing byte-identical input must produce identical
  output; that says nothing about the sorter's sensitivity to *small*
  perturbations, which is what a lossy codec makes. The honest error bar is
  the 100 s/600 s sign flip: **+-3 well-detected units**. Only the FP trend
  survives it. It is also a **three**-way control, not four: WavPack at
  6.0 bps is bit-exact on LSB-corrected data.
* **T.261 decode costs 6-10x more sorting wall time** (119-189 min vs 12-20
  min for blosc/WavPack on identical data). If the archive is re-read, decode
  dominates the deployment argument.
* **NP2 is not NP1 with finer pitch** — 99 % of its raw power is <300 Hz. A
  single spike-band profile applied to both is being evaluated on two
  different signals.
* **There is no LFP data in this repo.** All AIND streams are `AP*`. An LFP
  target needs a decision first: fetch the NP1 LF stream (2.5 kHz), or derive
  it by low-pass from NP2 wideband. Only the first is what anyone stores.
