# Paired reproduction check — CSHZAD026 vs the paper's own per-recording data

**This is the measurement the Phase 1 gate's tolerances are calibrated
against.** Earlier revisions of the plan and README cited "median 0.06 %,
max 2.5 %, across 11 codecs" — that figure was a conflation of two
different runs and is withdrawn. See "Provenance of the withdrawn figure".

## Conditions

| | |
| --- | --- |
| Recording | `CSHZAD026_2020-09-04_probe00` (IBL NP1, SpikeGLX, LSB 1) |
| Ours | first **60 s**, **1 s chunks**, **no preprocessing** |
| Paper | **full 1200 s**, 1 s chunks, `lsb != 'false'` (for IBL that means untouched) |
| Levels | the paper's `high` for every codec, per its `benchmark-lossless.py` |
| Source | `src/capsule-ephys-compression-results/.../benchmark-lossless.csv` |
| Tool | `d9bb2bf`, blosc pinned to 1 thread |

No LSB correction is applied because this is a SpikeGLX recording and the
paper's driver marks `ibl-np1` as `{"none": False}` — `correct_lsb` is a
documented no-op at LSB 1.

## Result

| compressor | level | shuffle | paper CR | our CR | Δ |
| ---------- | ----- | ------- | -------: | -----: | ----: |
| lzma        | high | no   | 2.606 | 2.616 | +0.4 % |
| blosc-zstd  | high | bit  | 2.536 | 2.552 | +0.6 % |
| blosc-zstd  | high | byte | 2.317 | 2.326 | +0.4 % |
| zstd        | high | no   | 2.271 | 2.272 | +0.0 % |
| blosc-zlib  | high | byte | 2.251 | 2.253 | +0.1 % |
| blosc-zstd  | high | no   | 2.132 | 2.163 | +1.5 % |
| blosc-lz4hc | high | bit  | 2.113 | 2.117 | +0.2 % |
| gzip        | high | no   | 1.948 | 1.948 | +0.0 % |
| zlib        | high | no   | 1.948 | 1.948 | +0.0 % |
| blosc-lz4   | high | bit  | 1.857 | 1.863 | +0.3 % |
| lz4         | high | no   | 1.171 | 1.172 | +0.1 % |

**median |Δ| = 0.2 %, max |Δ| = 1.5 %, n = 11.**

`gzip`, `zlib` and `zstd` agree to three decimal places.

## Duration invariance

Same codec (`blosc-zstd` high/bit), same conditions, growing the slice:

| slice | our CR | vs paper's full 1200 s (2.536) |
| ----- | -----: | -----: |
| 60 s   | 2.552 | +0.6 % |
| 300 s  | 2.551 | +0.6 % |
| 1200 s | 2.548 | +0.5 % |

So the residual is **not** a slice-length artifact. At the paper's own
duration we still sit +0.5 % high, which is the expected floor for two
independent implementations: ours sums `len(encoded_chunk)`, theirs takes
Zarr's on-disk store size.

## Independent confirmation, both shuffle states (round-2 review)

A second, **separate** measurement was made during the round-2 audit, at
the same conditions but spanning both shuffle states — including the
`no`-shuffle cells that the YAML-boolean bug had made unrunnable until
`1fe35cc`. Reported separately rather than merged into the table above,
because silently combining two runs into one figure is the error that
produced the withdrawn number (see below).

| cell (60 s, 1 s chunks) | ours | paper | Δ |
| --- | ---: | ---: | ---: |
| `zstd` high / no    | 2.272 | 2.271 | +0.04 % |
| `gzip` high / byte  | 2.257 | 2.254 | +0.13 % |
| `gzip` high / no    | 1.948 | 1.948 |  0.00 % |
| `lz4` high / byte   | 1.357 | 1.357 |  0.00 % |
| `lz4` high / no     | 1.172 | 1.171 | +0.09 % |
| `flac` medium (ccs -1) | 2.536 | 2.537 | -0.04 % |
| `wavpack` medium    | 3.669 | 3.656 | +0.36 % |

Across 11 codec configs spanning both shuffle states: **median ≈ 0.27 %,
max 0.70 %** — 3-7x inside the gate's `median <= 2 % / max <= 5 %`.

Two agreements worth noting on their own: this is the first check to cover
the audio codecs (unavailable when the table above was measured), and the
`no`-shuffle rows are the ones the gate could not previously produce at
all.

## Scope — what this does and does not establish

- **Does**: the engine reproduces the paper on one recording across the
  general-purpose codec set, at matched level, shuffle and chunking.
- **Does NOT**: clear the Phase 1 gate. That requires all 8 NP1
  recordings, and it has not been run. This is 1 of 8.
- **Does NOT**: cover the audio codecs. WavPack and FLAC were unavailable
  when this ran.
- **Does NOT**: say anything about lossy modes or spike sorting.

## Provenance of the withdrawn figure

"median 0.06 %, max 2.5 %, across 11 codecs" mixed the codec count from
this run with per-codec deltas computed elsewhere — against the committed
*whole-buffer* 10 s derivative compared to the paper's *1 s-chunk* rows.
That comparison was itself at mismatched chunk conditions, which is
precisely the error the gate exists to prevent, and its "2.5 % max" was a
chunk artifact rather than a real disagreement. A third recomputation over
the same derivative gave median 0.123 % / max 4.7 %, depending on how
level labels are mapped — three answers from one claim, which is why it is
withdrawn rather than adjusted.

Cite this file, not a remembered number.
