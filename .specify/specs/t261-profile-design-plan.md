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

| axis                          |  spike band (300-6000 Hz) |             LFP (<300 Hz) |
| ----------------------------- | ------------------------: | ------------------------: |
| temporal prediction gain      | **4.2-4.7 bits** (AR8-16) |      6.4-7.9 bits @30 kHz |
| cross-channel gain            |        **0.14-0.67 bits** |          **3.2-4.2 bits** |
| nearest-neighbour correlation |                 0.50-0.61 |                 0.75-0.96 |
| low-rank?                     |         no (PC1 = 7-16 %) | yes (top-4 PCs = 55-94 %) |
| correlation length            |                 50-100 um |                250-500 um |

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

Compact table first; the reasoning for each is below it. "Free" means no
increase in encoder time.

|   # | change                                              | expected                       | cost                 | Rung 0 measured           |
| --: | --------------------------------------------------- | ------------------------------ | -------------------- | ------------------------- |
|  H1 | drop the block-size / split-depth / delta-QP pins   | +2-8 % CR at equal distortion  | free                 | **refuted** -2.1 %, 3.5x  |
|  H2 | LSB-correct every Open Ephys input                  | CR 2.01 -> 3.53 (demonstrated) | free                 | untested (needs AIND)     |
|  H3 | `IntraPeriod` >= chunk length                       | unquantified                   | free                 | +0.2 %, 1.05x             |
|  H4 | `MAX_SPLIT_DEPTH=4..6`, `MaxAbsDeltaQP=1..3`        | +0.10-0.15 bits/sample         | encoder time         | **refuted** -0.1 %, 7-14x |
|  H5 | band-split <300 / 300-6000 Hz at independent QP     | up to 2-3x usable CR           | adapter work         | not run at rung 0         |
|  H6 | `ChannelDistortionScaleFactor` 0.5, 1.0             | FP reduction at matched CR     | needs seekable input | not run at rung 0         |
|  H7 | decorrelate error at fixed RMSE                     | FP headroom                    | encoder time         | not run at rung 0         |
|  H8 | cut encoder search effort                           | large speedup, small rate loss | free                 | **0.61x**, sorting TBD    |
|  H9 | LFP profile: joint channels, long blocks, low order | substantial                    | may be infeasible    | not run at rung 0         |
| H10 | try the ACoM and EMG presets as-is                  | free reference points          | free                 | not run at rung 0         |

**H1 — drop the pins.** The preset overrides the encoder's own lossy
defaults (§"Two verified findings"). Deleting three lines restores block
splitting, 256-sample blocks and per-block QP adaptation.

**H2 — LSB correction.** T.261 pays 3.43 bits/sample for zero information
and exploits the lattice least of all codecs tested. Note AIND NP1 is a
12-ADU lattice with +-1 jitter, so `cgps_allow_zero_lsb_flag` can capture at
most 2 of those 3.43 bits even when enabled — external correction is the
real fix.

**H3 — `IntraPeriod`.** 98304 samples is 3.28 s here against 384 s at EEG
rates, so adaptive state is destroyed ~3x per 10 s chunk. This also explains
why chunk size 10 s vs 60 s changes nothing today.

**H4 — adaptive splitting.** DCT gain saturates by N=64, so a short *fixed*
block buys little; the win is per-block **adaptivity**, worth +0.12 bits on
AP-band and +0.36 on wideband. Splitting lets RD pick long blocks in quiet
stretches and short ones on events, collecting both terms.

Two hard constraints, both verified at source and both easy to get wrong:
`MaxAbsDeltaQP+1` must be a power of two, so the legal values are
**0, 1, 3, 7, 15, 31, 63, 127** — not a range
(`StreamPacketBuilder.cpp:127`). And `MAX_SPLIT_DEPTH <= LOG2_MAX_BLOCK_SIZE
- 4` (`:79`), so depth is capped at **4** once H1 restores the auto block
size of 8. **H1 and a depth above 4 cannot both hold**; state the block size
each depth assumes.

**H5 — band splitting.** The only route to shaped error, since no
frequency-weighting knob exists. 50 % of spike-discriminative energy is
below 1 kHz and 80 % below 1.33 kHz, so the 300-6000 Hz band is about twice
as wide as the informative one.

**H6 — per-channel distortion.** Equalises error-to-noise across channels
whose sigma spans 4.5x (IBL) to 20x (NP2), matching the sorter's own
per-channel k*MAD threshold. Forces `max_abs_delta_qp_idx=7`.

**H7 — error structure.** FP inflation tracks the *structure* of the error,
not its magnitude. `TrellisQuantDelay>0`, `PerceptMode 1-3` and
`QuantMode 0` vs `2` all attack this and none has been swept.

**H8 — buy back compute.** Lossy is 4.2x *more* expensive than lossless
(52.3x vs 12.5x realtime), so the cost is encoder search — and distortion is
already at the uniform-quantiser bound, so search has little to protect.

**H9 — LFP.** The opposite prescription to spikes: cross-channel prediction
alone is worth 3.2-4.2 bits. Verify cost first — the joint-channel preset
timed out twice.

**H10 — untried presets.** ACoM is the only family tuned on kHz-rate data
and the only one enabling block splitting; EMG is spiky broadband.

**Do not pursue**, on the evidence:

* **Raising `LMS_ORDER`.** AR16 = 4.72 bits vs AR32 = 4.74 — saturated.
* **T.261 lossless.** WavPack lossless costs **1/37 the encode and 1/15 the
  decode** (paired per-recording medians). Note the CR comparison is closer
  than the pooled medians suggest: those medians straddle a bimodal raw/LSB
  population, and **paired, T.261 lossless wins 5 of 6 recordings** (3.112 vs
  3.071). The case against it is cost, not compression.
* **QP < 5.** Below CR 7.16 WavPack Hybrid does the same job for ~1/72 the
  compute. T.261's only defensible territory is **CR > 7.16**, above
  WavPack's hard rate ceiling.

## Enabling work — smaller than it first appeared

**The cfg-level hypotheses need no code changes.** `_resolve_cfg_dir()`
(`t261.py:76`) already honours a **`BWC_CFG_DIR`** environment variable, so
candidate `.cfg` files can live in the tool repo and be selected with
`preset=<candidate>`. H1, H3, H4, H6, H7, H8 and H9 are all cfg-level and
runnable today. Do not gate the programme on an adapter refactor. Two
qualifications: `BWC_CFG_DIR` is process-global, so all candidates in a
sweep must share one directory; and `describe()` records the cfg *path* but
not its bytes, so the one genuinely needed edit is a **cfg sha256 in the
manifest** — otherwise candidate identity is a filename.

`T261Adapter` still cannot forward arbitrary `--Key=Value` overrides, which
matters only for H5 (band splitting) and for anything wanting a per-cell
override rather than a per-cfg one.

Two operational notes, corrected:

* **The `.rec` file is a disk win, not a time win.** `WRITE_ENC_REC=1` writes
  a full reconstructed PCM file — 220 MB per 10 s chunk, verified on disk —
  but against ~456 s of encode that is ~0.5 MB/s, well under 1 % of the timed
  region. Suppressing it also is not free: `--BitstreamFile=-` sends the
  bitstream to **stdout**, requires an added `--LogFile=`, and collides with
  the progress tailer.
* **Skipping the pre-analysis costs two full re-reads, not four**, and the
  remedy is `--InputFileLength=<n_samples>` — which the adapter already
  knows and does not pass. `--RerefMode=0` does nothing here; it is consulted
  after both passes have already run and already defaults to 0.

## Rung 0 results — measured 2026-09-04

Ten candidates, one 10 s slice of `ibl-CSHZAD026` raw at QP 3.0, one chunk,
outside DataLad. `BWC_CFG_DIR` made the candidate cfgs resolvable with no
code change.

| candidate             | tests |     CR | vs stock | enc s |   cost |
| --------------------- | ----- | -----: | -------: | ----: | -----: |
| `r0-h3-intra`         | H3    | 6.2214 |   +0.2 % |   427 |  1.05x |
| `r0-h8-fast`          | H8    | 6.2094 |   +0.0 % |   250 |  0.61x |
| `r0-stock`            | --    | 6.2093 |     --   |   408 |  1.00x |
| `r0-zerolsb`          | H2    | 6.2093 |   +0.0 % |   405 |  0.99x |
| `r0-h4-b10d6`         | H4    | 6.2035 |   -0.1 % |  5902 | 14.47x |
| `r0-h4-b10d4`         | H4    | 6.2032 |   -0.1 % |  2962 |  7.26x |
| `r0-h4-b8d4`          | H4    | 6.1507 |   -0.9 % |  3257 |  7.99x |
| `r0-h1-auto-framepin` | H1    | 6.1455 |   -1.0 % |  1426 |  3.50x |
| `r0-h1-auto`          | H1    | 6.0779 |   -2.1 % |  1448 |  3.55x |
| `r0-h1-zerolsb`       | H1    | 6.0779 |   -2.1 % |  1439 |  3.53x |

**No candidate improved CR.** The spread from best to worst is 2.3 %, and the
two arms above stock are +0.2 % and +0.0 % — at n=1 recording, n=1 QP, n=1
window, neither is a result. The *cost* column is where the signal is: it
spans 24x and is unambiguous.

**H1 and H4 are refuted, and they fail the same way.** Both restore block
splitting; both cost multiples of stock and land at or below it. The
progression is monotone in split depth and monotone in the wrong direction:

    depth 0 (stock)   408 s   CR 6.2093
    depth 2 (H1)     1448 s   CR 6.0779
    depth 4 (H4)     2962 s   CR 6.2032
    depth 6 (H4)     5902 s   CR 6.2035

14x the encode time to arrive 0.1 % below the profile you started from. The
reasoning behind both — the preset overrides the encoder's own defaults,
therefore the defaults are better — inferred quality from provenance. The
pins are more plausibly the *output* of the preset authors' own tuning.
H1 was ranked first of ten.

**H8 is the only win, and it is a cost win.** Identical rate and identical
distortion — `rmse` 0.8687 and band-limited `rmse` 0.5013 agree to four
decimals with stock, and the file is 596 bytes *smaller* — for 61 % of the
encode time. This is consistent with the finding already recorded above:
distortion sits at the uniform-quantiser bound, so the encoder's RD search
is choosing between candidates that are all equivalent, and can be cut
without losing anything. H8 was ranked eighth of ten.

**H2 was not tested.** `r0-zerolsb` matches stock to four decimals because
`cgps_allow_zero_lsb_flag` has nothing to act on in SpikeGLX data, whose LSB
is 1. The arm needs an AIND recording (LSB 12) to mean anything — a
candidate/substrate pairing error in this rung, not a result.

**What this changes.** The programme was framed around finding CR headroom.
Rung 0 says that on this substrate there is none to find in the cfg
parameters, while a 39 % cost reduction was sitting in the hypothesis ranked
second-to-last. Since T.261's measured deployment blocker is cost (52x
realtime encode, and a 6-10x sorting penalty), H8 is worth more than the CR
gain the plan was hunting. Carry H8 into rung 1 as the new baseline, retire
H1 and H4, and re-run H2 against AIND before ranking it.

Determinism caveat: CR here is exactly reproducible (same encoder, same
input), so these differences carry no measurement noise. What they do not
carry is generalisation — one recording, one QP, one window. Rung 1's job is
to say whether H8's free speedup and H3's 0.2 % survive four QP points and a
second substrate.

## CORRECTION: H6 was never applied, and four arms tested dead code

Verified in the BWC source after three independent reviews. This supersedes
the H6 conclusion recorded below, which was wrong.

**`ChannelDistortionScaleFactor` is mis-indexed and cannot act per channel.**
`LambdaManager::analyzeOriginal` is called once with `InputNumChannels`
(384, global) and fills `m_channelLambdaScale[0..383]` with per-channel
variance ratios (`App/Encoder/Encoder.cpp:1275`, `StepSizeManager.h:54-91`).
But `getLambdaForChannel()` is called with the **group-local** channel index
(`BlockEncoder.cpp:2087`, inside `for (channel = 0; channel <
getNumChannels(); channel++)` where `getNumChannels()` is the *group's*
count), and `ChannelGroupSize: 1` builds 384 groups of one channel
(`Encoder.cpp:726-739`). **The local index is therefore always 0, and every
one of the 384 channels received channel 0's variance ratio.**

So the factor acted as a *uniform global* lambda scale, blended with the
fixed value at `StepSizeManager.h:90`, monotone in the factor. That predicts
exactly what was measured -- CR down, rmse down in proportion, normalised
spread unchanged, monotone in the setting -- and it means:

* **H6's per-channel hypothesis is UNTESTED, not refuted.** What was tested
  was a global lambda change.
* The earlier inference that "the knob works against its own hypothesis"
  attributed a rate-distortion shift to a failed redistribution mechanism.
  The measured numbers are equally consistent with the knob doing nothing
  per-channel at all, and only a correctly-indexed run separates the two.
* `r1-h6-ctrl` remains valid and still isolates the `MaxAbsDeltaQP` effect.

Testing H6 properly needs `ChannelGroupSize: 0` -- the only setting where
local and global indices coincide -- which is the arm that timed out twice;
or a ~2-line change passing each group's first global channel index into
`ChannelGroupEncoder` (which already receives `cgId`). This is arguably an
upstream BWC bug.

**Four of eight rung-0/1 arms varied structurally dead parameters**, which is
a systematic defect in how candidates were built rather than four
independent negatives. No one traced a knob to its consumer before spending
a cell on it:

* `cgps_allow_transform_skip: 0` makes the residual-mode list *exactly*
  `{TM_DCT}` (`PredictionEnc.h:1150-1192`). That kills
  `UseTrafoSignalAdapt`, `UseTrafoDiffs`, `UseTrafoSlope`,
  `UseTrafoHalfSlope`, `NumOptionsSignalAdapt`, `UsePreLPC`,
  `cgps_allow_verbatim_coding`, `cgps_allow_sample_pred_fixed_weights_flag`
  -- and `TrellisQuantDelay`, whose only consumer is inside
  `forwardSampleWiseTransformQuant` (`Transform.cpp:2117`), reached only by
  `TM_OFF` blocks. `r1-h7-trellis` did not test trellis quantisation; the
  code never ran.
* `PerceptMode` cannot fire on broadband data by design: the deblocking
  filter has an explicit low-passness veto (`Transform.cpp:2422-2477`) that
  bails when the first difference is comparable to the signal, which is what
  30 kHz wideband extracellular data is. The interesting branch also needs
  mode > 2 *and* `UseTrafoSignalAdapt: 1`; `r1-h7-percept` used mode 1.
* `ChannelGroupSize: 1` makes every cross-channel gate
  `(channel & chIndepMask) > 0` false, killing `UseLinearModel`,
  `UseBMOffsetPredPrevCh`, `UsePrevChSignalAdapt`, `UseLMSigFiltering`,
  `UseLMSigMultiHyp`, `cgps_allow_cc_lms_flag`,
  `cgps_max_order_cc_lms_minus_one`, `MaxNumMinus1PrevChSigAd` and
  `LMNumCandsFullRD`. **H8 is therefore a one-parameter change**:
  `NumOptionsSignalAdapt` was already 0 in stock and `LMNumCandsFullRD 3->1`
  gates a dead path, so all of its measured 0.61x is
  `BMNumCandsFullRD 2->1`. That matters for attributing its 15-FP swing.
* `r0-zerolsb` ran on IBL where the LSB is 1 (already recorded).

**A mechanism for the H1/H4 refutation.** `cgps_GetLmsOrder`
(`StreamPacketTypes.h:222-227`) scales the LMS AR order by the block's size
relative to the maximum: at `LMS_ORDER 16` and `LOG2_MAX_BLOCK_SIZE 10`, a
1024-sample block gets order 16 and a 256-sample block gets order 4.
Splitting buys per-block adaptivity by discarding 12 of the 16 predictor
taps that carry most of the gain. Block size and predictor order are not
separable knobs in this codec, which is a better explanation than "the pins
are the authors' tuning" and means any future partitioning hypothesis is
dead unless it raises `LMS_ORDER` proportionally.

Also corrected: `combinedPresetEMG_IndepChannel.cfg` is **byte-identical**
to `combinedPresetEEG_IndepChannel.cfg`, so H10's EMG arm is a guaranteed
no-op; but `combinedPresetECG_IndepChannel` *is* lossy and differs from
stock in only four parameters, so H10 has a lossy reference point after all.
`UseTrafoSkip` is in the cfg allow-list but read nowhere -- a dead key.
`ChIndepIntMask` is hard-wired to 511 and absent from the allow-list, so it
cannot be set at all.

## Rung 0 follow-up — H8 across QP, and the LSB audit

Rung 0 left two loose ends: its one positive finding rested on a single QP
point, and its zero-LSB arm had been run on IBL, where the flag cannot act.
Both are now closed, and closing the second turned into an audit of every
recording family in the study.

### H8 generalises

|  QP | stock CR |   H8 CR |     dCR | stock s | H8 s |  cost |
| --: | -------: | ------: | ------: | ------: | ---: | ----: |
| 1.0 |   3.7115 |  3.7115 | -0.00 % |     259 |  153 | 0.59x |
| 3.0 |   6.2093 |  6.2094 | +0.00 % |     405 |  250 | 0.62x |
| 5.0 |   9.0188 |  9.0189 | +0.00 % |     400 |  243 | 0.61x |
| 8.0 |  16.7720 | 16.7728 | +0.00 % |     368 |  222 | 0.60x |

Identical CR to four decimals across a 4.5x CR range, at 0.59-0.62x cost
throughout -- including QP 1.0, where fine quantisation might have given the
RD search something to protect. It does not. AIND agrees (448 s -> 280 s), so
this is not IBL-specific. **A ~39 % encode-time reduction at statistically
indistinguishable fidelity.**

That wording is deliberate, and replaces an earlier "for nothing" that the
evidence did not support. The H8 bitstream is 596 bytes *smaller* than
stock's, so the decode is **not** bit-identical: 3.06 % of samples differ,
and those differences are 7.4x enriched on the high-amplitude samples that
carry spikes (22.76 % of |x| > 5 sigma differ, against 3.06 % overall;
124 of 384 channels touched). Equal aggregate RMSE does not imply equal
error *distribution*, and spike detection responds to the latter.

Stratifying reconstruction error by amplitude shows the differences are
symmetric rather than a degradation:

    stratum         n samples     stock   h8-fast   h8/stock
    -------------  ----------  --------  --------  ---------
    all           115200000     0.86866   0.86873    1.0001x
    |x| > 1 sigma  34575366     0.86896   0.86903    1.0001x
    |x| > 3 sigma   1347113     0.86642   0.86639    1.0000x
    |x| > 5 sigma     75854     0.88036   0.87694    0.9961x
    |x| > 8 sigma     11308     0.89084   0.89747    1.0074x

Max |err| is 6.0 for both; H8 is worse on 1.4350 % of samples and better on
1.4273 %. The two departures from 1.0000 sit at the smallest strata and flip
sign, at ~1.5 and ~1.1 standard errors -- noise, not a trend. **No evidence
of systematic fidelity loss, but this is amplitude as a proxy for spikes on
a slice with no ground truth.** Sorter output is not a smooth function of
reconstruction error, so H8 is not established as free until the 600 s
MEArec sorting arms run.
Since T.261's measured blocker is cost, not ratio, this is worth more than
the CR headroom the programme was built to hunt. H8 was ranked eighth of ten.

### `cgps_allow_zero_lsb_flag` is inert, not partially effective

On AIND 634568 -- which does carry a real 12-lattice -- flag on and flag off
give identical CR, identical encode time and identical RMSE. The plan
previously estimated the flag "can capture at most 2 of those 3.43 bits";
the measured figure is zero. External correction is the only route to H2.

### The lattice spectrum

Exact-fraction / chance ratio, after per-channel median removal. A genuine
lattice at L shows a peak at L *and* at every divisor of L -- that divisor
signature is what distinguishes a lattice from a coincidence:

|  L | AIND NP1 | AIND NP2 (x2) | IBL NP1 | MEArec NP1 | MEArec NP2 |
| -: | -------: | ------------: | ------: | ---------: | ---------: |
|  2 |    1.72x |         1.00x |   1.02x |      2.00x |      1.00x |
|  3 |    2.58x |         1.00x |   1.01x |      3.00x |      2.99x |
|  4 |    3.44x |         1.01x |   1.03x |      4.00x |      1.00x |
|  6 |    5.17x |         1.01x |   1.05x |      6.00x |      2.99x |
|  8 |    3.52x |         1.02x |   1.09x |         -- |         -- |
| 12 |   10.33x |         1.05x |   1.22x |     12.00x |      2.99x |
| 16 |    3.58x |         1.04x |   1.41x |         -- |         -- |

AIND NP1 is unambiguous: divisors of 12 (2, 3, 4, 6, 12) all sit at exact
frac 0.8612 while non-divisors 8 and 16 collapse to 0.4395 and 0.2241.
MEArec NP1 is a *perfect* 12-lattice and MEArec NP2 a 3-lattice, so both
`configs/datasets/mearec-np*-100s.yaml` are correct and the sorting results
are unaffected. IBL is correctly null -- it is the control that makes the
rest of the table trustworthy.

**AIND NP2 has no lattice at any L, on two independent sessions**, yet the
paper assigns it LSB 3 and its own paired rows show +20 % CR from
"correcting" it. Dividing by 3 there discards ~1.58 bits of real signal.
`configs/profiles/t261-vs-paper-codecs.yaml` uses only AIND NP1 and IBL, so
no cell in this study is affected -- but half the paper's NP2 lossless rows
(1800 of 3600) rest on it.

### What the paper's LSB gain is actually made of

blosc-zstd level 5 bitshuffle, 1 s of each recording, gain decomposed into
its two steps:

| step                | NP2 CR |  x raw | NP1 CR |  x raw |
| ------------------- | -----: | -----: | -----: | -----: |
| raw                 | 1.4518 | 1.0000 | 1.9270 | 1.0000 |
| median removal only | 1.6255 | 1.1196 | 1.9788 | 1.0269 |
| divide by L only    | 1.7208 | 1.1853 | 2.4833 | 1.2887 |
| paper recipe (both) | 1.8590 | 1.2805 | 2.5166 | 1.3060 |

On NP1 the +28.9 % from dividing by 12 is legitimate -- the lattice is there.
On NP2 the +18.5 % is not.

### The correction is mildly lossy on real AIND data, and quantifiably so

AIND NP1's lattice is dithered, not exact:

    deviation from lattice     share
    -------------------------  --------
     0 ADU                     86.1169 %
    -1 ADU                      6.9564 %
    +1 ADU                      6.8835 %
    |dev| <= 1                 99.9567 %

RMSE of the discarded jitter is 0.3751 ADU = **0.3266 % of signal sigma**.
The plan's "12-ADU lattice with +-1 jitter" was exactly right. So an AIND
`-lsb` cell is lossless with respect to the *corrected* signal while
carrying 0.33 % of sigma in preprocessing loss relative to what is stored --
and `expected_lossless = not adapter.lossy` (`runner.py:200`) is codec-only,
so those cells report `lossless = T`. That is faithful to the paper, which
reports the same way, but it is worth an explicit note wherever AIND
`-lsb` CRs sit beside genuinely lossless IBL ones.

### One implementation trap

The lattice has an **arbitrary per-channel phase**: median residues span all
twelve values and only 8.85 % are multiples of 12. So plain median removal
recovers the lattice (0.8612) while snapping the median to a multiple of 12
destroys it (0.0887, i.e. chance) -- as does not removing it at all. Removing
the per-channel modal residue instead gives the identical 0.8612, confirming
the mechanism. The paper's median-first recipe is correct and must not be
"improved" by rounding the offset to the lattice.

## The sorting reference, and which endpoints can be believed

Measured from `derivatives/sorting-2026-08-26-sorting-eval-t261-600s`
(600 s MEArec NP1, lsb 12, chunk 1.0 s, Kilosort 4, 100 GT units). Any
profile judged on sorting is judged against these.

| arm                                    |       CR | well |  FP | redun |    acc |
| -------------------------------------- | -------: | ---: | --: | ----: | -----: |
| bittrunc bits=0 (lossless)             |    3.347 |   96 | 126 |    23 | 0.9809 |
| blosc-zstd level 9 byte (lossless)     |    2.933 |   96 | 126 |    23 | 0.9809 |
| t261 lossless preset                   |    3.721 |   96 | 126 |    23 | 0.9809 |
| t261 QP 1.5                            |    4.270 |   94 | 129 |    26 | 0.9581 |
| t261 QP 2.0                            |    4.829 |   98 | 133 |    26 | 0.9863 |
| t261 QP 3.0                            |    5.989 |   98 | 138 |    22 | 0.9862 |
| t261 QP 5.0                            |    8.575 |   96 | 145 |    30 | 0.9734 |
| t261 QP 8.0                            |   14.514 |   99 | 184 |    23 | 0.9891 |
| wavpack 2.25 bps                       |    7.101 |   97 | 131 |    24 | 0.9818 |
| wavpack 2.5 bps                        |    6.746 |   95 | 135 |    24 | 0.9740 |
| wavpack 3.0 bps                        |    5.759 |   94 | 128 |    22 | 0.9670 |
| wavpack 4.0 bps                        |    4.450 |   97 | 143 |    23 | 0.9859 |
| wavpack 6.0 bps                        |    3.734 |   96 | 126 |    23 | 0.9809 |
| bittrunc bits=4                        |   29.098 |  100 | 353 |    37 | 0.9946 |
| bittrunc bits=5                        |  337.411 |   77 | 923 |   303 | 0.8467 |
| bittrunc bits=6                        | 1939.651 |   20 | 644 |   194 | 0.3856 |
| bittrunc bits=7                        | 4884.255 |    4 | 588 |    44 | 0.1215 |

**The null control passes.** Three unrelated lossless codecs land on
identical endpoints (96 / 126 / 23 / 0.9809), so the pipeline is not
measuring its own noise and a difference between arms is attributable to the
codec. The positive control passes too: bit truncation collapses from 96
well-detected to 4.

**FP is the endpoint to read; `well_detected` is not.** Across the T.261 QP
sweep FP is monotone in distortion -- 129, 133, 138, 145, 184 -- while
`well_detected` scatters non-monotonically -- 94, 98, 98, 96, 99 -- and is
*higher* at QP 8.0 than at QP 5.0 despite 2.4x the rate reduction. WavPack
scatters the same way (97, 95, 94, 97, 96). So **+-2 well-detected units is
noise**, and a profile claim resting on it is not a claim. The same caution
applies to `accuracy`, which tracks `well_detected`.

**A caution about bittrunc bits=4**: 100/100 well-detected, better than
lossless, with FP nearly tripled (353). Aggressive distortion can *raise*
the well-detected count while wrecking precision, which is why the paper's
own criterion is a waveform-feature distribution and not a unit count.

Reproduces the study's headline trade exactly: T.261 QP 5.0 is +19 FP over
lossless at CR 8.575; WavPack 2.25 bps is +5 FP at CR 7.101.

## H5 as specified is refuted — quantisation error is not band-limited

Implemented as `t261-bandsplit` (`src/compbench/codecs/t261_bandsplit.py`),
split exact by construction (`lo_i + hi == x` bit-for-bit; lossless arm
round-trips at rmse 0). 10 s of `ibl-CSHZAD026` raw, QP 5.0 on the spike
band throughout, `qp_lo` swept:

| arm                       |     CR |  total | spike 300-6k | LFP <300 |  >5sig |
| ------------------------- | -----: | -----: | -----------: | -------: | -----: |
| plain t261 qp=5 (ref)     | 9.0188 | 1.4516 |       0.8160 |   0.1786 | 1.5077 |
| bandsplit qp_lo=5  hi=5   | 8.7863 | 1.5119 |       0.8790 |   0.2517 | 1.6182 |
| bandsplit qp_lo=20 hi=5   | 9.0884 | 1.7955 |       0.9637 |   0.8379 | 2.1081 |
| bandsplit qp_lo=40 hi=5   | 9.2205 | 2.3894 |       1.0443 |   1.6653 | 3.0574 |

Coarsening the low band does buy rate: CR 8.7863 -> 9.2205, clearing the
2.6 % two-encode handicap and reaching +2.2 % over plain T.261. **But
spike-band error rises monotonically with it** -- 0.8160 -> 1.0443, +28 % --
and >5 sigma error +103 %. Bandsplit is worse than plain T.261 on spike
fidelity at *every* setting tested, including matched QP.

**Why this is fundamental, not a tuning failure.** Quantisation error of a
band-limited signal is not itself band-limited. Coarsely quantising the low
band injects error across the whole spectrum, so a fraction always lands in
300-6000 Hz however sharp the crossover; no cutoff or filter order fixes it.
(The measured leak is smaller than white-noise theory predicts, because
T.261's prediction shapes its error and a smooth low band predicts well --
but it is real and monotone.)

So **H5 as the plan specifies it -- "band-split <300 / 300-6000 Hz at
independent QP" -- is refuted.** The premise that bits spent below 300 Hz
are invisible to the sorter is true of the *signal* and false of the
*quantisation error*.

**The one variant with a valid mechanism is decimation.** Decimate the low
band to ~1 kHz before coding it: its quantisation error is then confined
below the new Nyquist by the interpolation filter, by construction rather
than by hope, and the sample count drops ~30x so the two-encode handicap
becomes ~1.03x instead of 2x. The cost is that exact reconstruction is lost
(upsampling cannot reproduce the rounded low band), so the lossless null
control this implementation currently passes would have to be replaced by a
measured error floor. That is a different proposal and should be ranked
against the reviewers' candidates rather than assumed to be next.

Caveat that would have applied even had it worked: this is a
sorting-oriented profile that deliberately degrades the LFP band, which the
study treats as a separate use case. It could never have been reported as a
strict improvement.

## Staged search

`rmse = QP/sqrt(12)` holds to 0.91-1.06x across 30 lossy cells — **but only
for the stock preset**, because `MaxAbsDeltaQP=0` and
`ChannelDistortionScaleFactor=0` make the step uniform over every block and
channel. H4, H6, H7 and H5 each break that by construction, which is four of
the ten hypotheses and includes the highest-ranked ones after H1-H3.
**Measure distortion for every candidate**; `rmse` is already in every
`metrics.json`, so this costs nothing but must not be skipped.

| rung | substrate                        | gate                          | budget each            |
| ---- | -------------------------------- | ----------------------------- | ---------------------- |
| 0    | 10 s, 1 chunk                    | validity, determinism, cost   | ~0.3 cell-h            |
| 1    | 60 s MEArec, 4 QP points         | rate at matched distortion    | ~3.5 cell-h            |
| 2    | 2nd window + NP2 + one real rec  | rank stability                | ~10 cell-h             |
| 3    | **600 s MEArec, sorting**        | FP and well-detected bounds   | ~19 cell-h + 3.5 h GPU |
| 4    | real recordings, no ground truth | agreement vs lossless sorting | confirmation only      |

Rung 0 rejects a candidate whose encode cost exceeds 1.5x stock or whose
projected chunk time exceeds a quarter of the timeout — a cost gate that does
not exist today, and whose absence already cost one abandoned arm. Rung 3's
gate is FP <= 126+17 and well-detected >= 96-4, plus CR strictly greater than
stock at equal waveform p90.

Rungs 1-2 are **sorter-free by design**: short slices are *biased*, not
merely noisy — 6 of 10 arms reversed the sign of an endpoint between 100 s
and 600 s, and a biased proxy cannot be averaged out. Sorting is 600 s or it
is not evidence.

**Ranking uses rate at matched distortion; the waveform-feature p90 is the
acceptance gate, not the ranking metric.**

An earlier draft justified this with "band-limited RMSE predicts FP
inflation perfectly (Spearman +1.000, n=5)". That is **tautological and must
not be relied on**: the five points are one monotone QP sweep, band-limited
RMSE is strictly increasing in QP, so *any* monotone function of QP scores
+1.000. It says nothing about ranking candidates that differ in block size,
split depth or quantiser — which is the whole job of rungs 1-2. Worse, four
of the five FP inflations (+3, +7, +12, +19) sit inside the study's own
stated +-17 noise floor; only QP 8.0's +58 clears it. The concordance
between the cheap gate and the sorting endpoint is therefore **assumed, not
demonstrated** — which is exactly why the two carried-forward rejected
candidates at rung 3 are mandatory rather than nice to have.

Carry **2 rejected candidates into rung 3 anyway.** Without them the staged
design cannot be falsified.

## The error budget, in the units that matter

Express the target as **error-to-noise ratio per channel**, never absolute
uV and never bps:

| error RMS / sigma_noise | outcome                                       |
| ----------------------: | --------------------------------------------- |
|                 <= 0.15 | FP inflation under ~10 %                      |
|                 <= 0.33 | practical edge (+58 FP at QP 8.0)             |
|               0.54-0.63 | **cliff** — well-detected collapses 100 -> 77 |

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

## What the adversarial review changed

An independent reviewer checked every load-bearing claim against source and
committed data. **Both headline findings were confirmed** — the preset does
override the encoder's lossy defaults, and no frequency-weighting mechanism
exists in BWC. So did `rmse = QP/sqrt(12)`, the cost ratios, the in-band
error fractions, the delta-filter result, the `IntraPeriod` mis-scaling, and
the ADC-multiplexing argument (which it found *stronger* than stated:
`Prediction.h:795-830` reads the previous channel at the same index with no
offset search at all, and a fractional-sample skew is not diagonal in the
DCT, so the codec cannot compensate even in principle).

What it refuted or sharpened, beyond the inline fixes above:

* **The mechanism in finding 2 is not load-bearing for sorting.** At matched
  CR, T.261 carries ~2x *lower* in-band error than WavPack (0.80-0.82 vs
  1.34-1.74) and still produces **more** false positives (+19 at CR 8.58 vs
  +5 at CR 7.10). Spectrally flat error explains T.261's lower waveform
  error; it does not explain the sorting endpoint, and this plan should not
  imply it does. Most of the T.261/WavPack in-band gap is WavPack's error
  being *actively* signal-weighted, not T.261's being shaped.
* **A cheaper route to shaped error than H5.** `TrQuant::quant()` takes a
  scalar RD lambda per block (`PredictionEnc.h:665`). Making it a vector over
  coefficient index — biasing RDOQ to preserve 300-6000 Hz — is an
  encoder-only change that leaves the bitstream conforming and the stock
  decoder unaffected. ~10 lines against H5's whole band-split adapter. The
  "never patch `src/bwc/`" rule protects the subdataset pin; it is repo
  hygiene, not a research constraint, and a branch satisfies it.
* **A free arm the plan missed.** `cgps_allow_zero_lsb_flag` is **0 in the
  lossy preset** and 1 in the lossless one, so every lossy T.261 number in
  this study was produced with zero-LSB detection off. Flipping it is a
  one-line arm and the natural companion to H2.
* **The error-budget cliff is at 0.54, not 0.54-0.63**, if judged on FP —
  the plan's own gate metric. bittrunc-4 sits at 0.54 with well-detected 100
  but **FP 353 against a baseline of 126**. The table showed only the
  well-detected collapse. Also `<=0.15 -> under ~10 %` is violated by WavPack
  4.0 bps (0.120, +17 FP = 13.5 %), and no T.261 arm exceeds 0.33, so the
  cliff region is extrapolated from a different, non-dithered error process.
* **H1 is not free and changes a fourth thing.** `Log2FrameLength` defaults
  to `LOG2_MAX_BLOCK_SIZE + 3`, so dropping the block pin shrinks the frame
  from 8192 to 2048 samples — 4x more frequent frame boundaries, which could
  hurt. Restoring split depth and delta-QP search is additional RD search by
  definition.
* **ACoM is not the only preset enabling splitting** — ECG and lossless EMG
  set `MAX_SPLIT_DEPTH: 1`; only the EEG family and lossy EMG pin it to 0.
  And there is **no lossy ACoM preset**, so H10 gives a lossless reference
  point only.
* **The joint-channel timeout is a cost, not a block.** It was the *lossless*
  preset against a 1800 s limit that no longer exists — the default is now
  7200 s, so the arm is runnable at >180x realtime.
* **H6 equalises against the wrong sigma.** `analyzeOriginal` accumulates
  **wideband** per-channel variance, while the sorter's threshold is on the
  300-6000 Hz bandpass. On LFP-dominated real data these diverge; on MEArec
  (no LFP) they coincide, so a MEArec test of H6 will look good and
  generalise badly.
* **The `inter_sample_shift` remedy is under-powered.** BWC ships exactly two
  prediction filters, one zero-shift and one **half**-sample
  (`CommonROM.h:51-54`). One half-sample option cannot cover 12 phases
  spanning 0.92 samples. Resampling channels onto a common time base before
  encoding is the cheaper, codec-independent experiment — and would help
  blosc and WavPack cross-channel too.
* **The four source reviews are not committed**, so every number in "Where
  the redundancy is", the MEArec spectral caveat, and the per-channel sigma
  spans are unverifiable from this repo. Commit the reviews or their
  computations before anyone relies on them.
* **LFP is a stub, correctly.** Fetching the NP1 LF stream is a prerequisite
  work item, not a caveat, and H9 is unactionable until it exists.

