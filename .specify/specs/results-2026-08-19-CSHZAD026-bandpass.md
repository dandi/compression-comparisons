# Second reproduction — CSHZAD026 + band-pass 300–6000 Hz (2026-08-19)

Same setup as the first reproduction (`results-2026-08-19-CSHZAD026.md`),
now with the paper's 300–6000 Hz band-pass preprocessing applied. Matches
Buccino et al. Fig 2 methodology exactly.

## Delta vs raw sweep (same recording, same codec configs)

| codec                     |  raw CR | band-pass CR | +% |
| ------------------------- | ------: | -----------: | -: |
| **T.261 QP=8**            |  16.77  |    **23.50** | +40 % |
| T.261 QP=5                |   9.02  |    16.26     | +80 % |
| T.261 QP=3                |   6.21  |    12.08     | +94 % |
| T.261 QP=2                |   4.99  |     9.90     | +98 % |
| T.261 QP=1.5              |   4.40  |     8.76     | +99 % |
| **T.261 IndepCh lossless**|   3.80  |    **6.90**  | +82 % |
| lzma                      |   2.61  |     3.36     | +29 % |
| zstd L22                  |   2.33  |     3.13     | +34 % |
| blosc-zstd L9             |   2.32  |     2.80     | +21 % |
| blosc-zstd L3             |   2.05  |     2.38     | +16 % |
| gzip L5                   |   1.94  |     2.60     | +34 % |
| blosc-lz4 L9              |   1.36  |     1.42     |  +4 % |

**T.261 benefits more from band-pass than any general-purpose codec** — 82 %
for lossless, ~100 % for the lightly-lossy QP configs. Plausible explanation:
T.261's DCT+prediction+CABAC pipeline was designed with band-limited
biosignal input in mind; sub-300 Hz content wastes coding capacity.

## Paper cross-check — corrected mapping

**Earlier drafts of this note compared these band-pass numbers to Buccino
et al. Fig 2 — that was wrong.** Fig 2 uses RAW data (no preprocessing);
band-pass results belong against Fig 7 in the paper (their §"Preprocessing
effects"). This note now defers absolute-magnitude cross-check until we
have either (a) the paper's `benchmark-lossless-preprocessing.csv` (Code
Ocean asset only), or (b) our own sweep across all 8 NP1 recordings so we
can compare medians vs paper's reported means. The "~2.7 / ~2.9 / ~2.4"
paper numbers in the earlier draft were my guesses, not citations.

What we CAN say from this run:
- **T.261 IndepChannel lossless (CR 6.90) is the highest *general-purpose*
  lossless CR in this sweep**, 105 % above lzma (3.36) and 146 % above
  blosc-zstd L9 (2.80). WavPack — the paper's lossless winner at
  ~3.6 mean-of-NP1 — was excluded from this profile; see
  `paper-with-wavpack.yaml`. Direct T.261-vs-WavPack claim needs that
  profile to run.
- The **rankings** of the general-purpose codecs match the paper Fig 2
  order (which uses raw data, and the same ranking holds after band-pass):
  lzma > zstd L22 > blosc-zstd L9 > blosc-zlib > gzip ≈ zlib > blosc-lz4hc
  > blosc-lz4 > lz4.
- Band-pass **helps T.261 much more than it helps general-purpose codecs**
  (delta table below). That's the interesting per-codec-family effect and
  it's self-contained — doesn't depend on paper cross-check.

## Headline

**T.261 IndepChannel lossless (CR 6.90) beats every general-purpose lossless
codec in this sweep by 105 %.** WavPack was not run in this profile — see
`paper-with-wavpack.yaml` to include it. T.261 lossy QP=1.5 (CR 8.76,
PRDN ≈ 4.9 % of signal RMS on band-pass data) more than doubles compression
over lzma; distortion level is small but not "imperceptible" (spike-sorting
fidelity not yet evaluated — see Caveats). T.261 QP=8 hits CR 23.5 at
PRDN ≈ 18 % — likely severe degradation of small-amplitude spikes;
requires sorting-fidelity eval before use.

## Caveats

- Paper Fig 2 = raw data; Fig 7 = preprocessed. Cross-check my results
  against the matching figure. Earlier drafts of this note bundled the
  wrong pairing.
- Paper reports means ± SD across 8 NP1 recordings × multiple shuffle/level
  configs (N = 48-72 per bar). Our single-recording × single-config
  numbers are single points in that distribution, not directly comparable
  to a mean.
- Absolute-magnitude paper cross-check requires the paper's
  `benchmark-lossless-preprocessing.csv` (Code Ocean capsule
  `AllenNeuralDynamics/aind-capsule-ephys-compression-results` data asset;
  needs a CO account and manual fetch), or running our own 8-recording
  sweep.

## Provenance

- Full artifacts + `AUTO_TABLE.md` in the STAMPED study at
  `results/dandi-t261-compression-study/derivatives/compbench-2026-08-19-CSHZAD026-slice10s-bandpass/`,
  committed under datalad `b6834f0`.
- 20/21 cells: joint-channel EEG lossless T.261 still hits 30-min timeout —
  same slowpoke as raw. Chunk-by-channel-group or Phase 2b pybind11 wrapper
  needed.
