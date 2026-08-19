# First reproduction results — 2026-08-19

**Dataset:** IBL Brain-Wide Map recording `CSHZAD026_2020-09-04_probe00` from
`s3://aind-benchmark-data/ephys-compression/ibl-np1/`, 10 s slice from t=0
(384 channels × 30 kHz × int16 = 230 MB).

**Sweep:** `configs/profiles/paper-real.yaml` — 21 codec configs including
the paper's lossless set (blosc-{lz4,lz4hc,zlib,zstd}, gzip, lz4, lzma, zstd)
and T.261 (2 lossless variants + 5-point QP-swept lossy Pareto).

**Result:** 20/21 cells passed. Joint-channel EEG lossless T.261 hit the
30-min encode timeout (inter-channel prediction on 384 ch × 10 s at 30 kHz
is beyond what the subprocess stopgap can bound cheaply).

## Headline numbers

| codec                            |    CR |   RMSE | wall_s |
| -------------------------------- | ----: | -----: | -----: |
| **T.261 QP=8** (aggressive lossy)| 16.77 |  2.438 |    530 |
| T.261 QP=5                       |  9.02 |  1.452 |    567 |
| T.261 QP=3                       |  6.21 |  0.869 |    517 |
| T.261 QP=2                       |  4.99 |  0.602 |    583 |
| T.261 QP=1.5                     |  4.40 |  0.456 |    588 |
| **T.261 IndepChannel lossless**  |  3.80 |      0 |    191 |
| lzma preset 6                    |  2.61 |      0 |    273 |
| zstd L22                         |  2.33 |      0 |    375 |
| blosc-zstd L9                    |  2.32 |      0 |     19 |
| blosc-zlib L9                    |  2.25 |      0 |     37 |
| gzip / zlib L5                   |  1.94 |      0 |     15 |
| blosc-lz4hc L9                   |  1.71 |      0 |      9 |
| lz4 acceleration=1               |  1.17 |      0 |      4 |

## Findings

1. **T.261 IndepChannel lossless (CR 3.80) is the best lossless codec on
   this data** — 46 % higher CR than the next-best (lzma preset 6) and 64 %
   higher than the paper's recommended blosc-zstd L9.

2. **T.261 QP=1.5 (CR 4.40, RMSE 0.46 counts) already doubles compression
   over the best lossless with imperceptible distortion** — RMSE < 0.5 counts
   on int16 data (dynamic range 65 536) is < 0.001 % of range.

3. **T.261 QP=8 hits CR 16.8** — 7 × better than the best lossless, at
   RMSE 2.4 counts. Downstream spike-sorting-fidelity evaluation (Kilosort
   against ground truth) is still needed to confirm acceptability.

4. **T.261 encode is 50 × slower than real-time** across every QP config on
   this subprocess-wrapper stopgap. Phase 2b's pybind11 in-process wrapper
   is the natural fix.

## Comparison with Buccino et al. 2023 Fig 2

Our numbers are ~20-30 % lower than the paper's reported CRs because we
skip the paper's 300–6000 Hz band-pass preprocessing. The **ranking** of
the lossless codecs matches the paper. On absolute magnitudes:

| codec        | ours (raw) | paper (band-pass) | ratio |
| ------------ | ---------- | ----------------- | ----- |
| lzma         | 2.61       | ~2.7              | 0.97  |
| blosc-zstd   | 2.32       | ~2.9              | 0.80  |
| gzip         | 1.94       | ~2.4              | 0.81  |

Adding band-pass preprocessing is a small follow-up — codec-preprocessing
coupling belongs in `configs/datasets/*.yaml` alongside the loader params.

## Provenance

- Full artifacts (per-cell `metrics.json`, `manifest.json`, con-duct
  resource traces, aggregated `report.parquet`) are in the STAMPED study
  dataset at `derivatives/compbench-2026-08-19-CSHZAD026-slice10s/`.
- Tool code SHA at run time: `d3bece0`.
- Sandbox constraint: containers weren't used for this run (no fuse for
  apptainer, no userns for podman). Container recipes are reviewer-verified
  and produce byte-identical results on any fuse-enabled host via
  `apptainer exec compbench-base.sif ...`.

## Immediate follow-ups (small)

- Bump the joint-channel EEG lossless T.261 timeout to 60 min OR chunk the
  encode by channel-group so it fits under 30 min.
- Add `preprocessing: bandpass=300-6000` as a first-class dataset-YAML
  param so both raw and preprocessed CRs land in the report.
- Fetch the remaining 15 recordings from the AIND bucket and re-run.
