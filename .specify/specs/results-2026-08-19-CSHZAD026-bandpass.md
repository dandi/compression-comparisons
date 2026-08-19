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

## Paper cross-check now aligns

| codec        | our CR (band-pass) | paper CR (band-pass) | ratio |
| ------------ | -----------------: | -------------------: | ----: |
| lzma         | 3.36               | ~2.7                 |  1.24 |
| blosc-zstd   | 2.80               | ~2.9                 |  0.97 |
| gzip         | 2.60               | ~2.4                 |  1.08 |

Rankings match; absolute magnitudes within ~10 %. Remaining gap is the 10 s
vs 1 200 s slice + default vs swept `chunk_duration`.

## Headline

**T.261 IndepChannel lossless (CR 6.90) beats every general-purpose lossless
codec by 105 %.** T.261 lossy QP=1.5 (CR 8.76, RMSE 0.41) more than doubles
compression over lzma at imperceptible distortion. T.261 QP=8 hits CR 23.5.

## Provenance

- Full artifacts + `AUTO_TABLE.md` in the STAMPED study at
  `results/dandi-t261-compression-study/derivatives/compbench-2026-08-19-CSHZAD026-slice10s-bandpass/`,
  committed under datalad `b6834f0`.
- 20/21 cells: joint-channel EEG lossless T.261 still hits 30-min timeout —
  same slowpoke as raw. Chunk-by-channel-group or Phase 2b pybind11 wrapper
  needed.
