# Project instructions

## Markdown tables must be readable as plain text

Every Markdown table this project emits — reports, result summaries, design
docs, commit-message tables, anything — must have its columns padded with
spaces so the raw `.md` is legible without a renderer. These files are read
in terminals, diffs and PR reviews far more often than they are rendered.

Do this:

    | dataset           | codec      |    CR | lossless |
    | ----------------- | ---------- | ----: | :------: |
    | ibl-CSHZAD029-raw | blosc-zstd | 2.484 |    T     |
    | aind-634568-lsb   | wavpack    | 7.120 |    F     |

Not this:

    | dataset | codec | CR | lossless |
    | --- | --- | ---: | :---: |
    | ibl-CSHZAD029-raw | blosc-zstd | 2.484 | T |

Rules:

* Pad every cell to the width of the widest cell in its column.
* Pad the separator row to the same width, keeping the alignment colons
  (`---:` right, `:---:` centre, `---` left).
* Right-aligned numeric columns get their values right-padded to the column
  width so the digits line up vertically.
* This applies to generated output too, not just hand-written files: a
  renderer that emits ragged tables is a bug to fix in the renderer, not
  something to tidy up afterwards.

## Never commit to the study dataset while a sweep is running

`results/dandi-t261-compression-study/` is the DataLad dataset the per-cell
`datalad run` records live in. Any commit landing on its branch during a
sweep falls inside some in-flight cell's run window, and that cell fails
with:

    command created commits that include files not declared as --output:
      ['.gitignore', 'code/partial_report.sh', ...]

Snakemake then *deletes that cell's completed outputs* as possibly corrupt,
so finished compression work is thrown away. This is a documented non-goal
upstream: a plain `git commit` from another process is indistinguishable
from commits made by the command itself.

Cost the first time: 4 cells, each of which had already finished and
reported `round_trip_ok=True`.

So, while any sweep is in flight:

* Do not `git commit` in the study dataset. Not scripts, not `.gitignore`,
  not notes. It is not enough to leave the pinned tool submodule alone.
* Write anything new to a gitignored path (`.partial-reports/`), or to the
  tool repository, which is a separate git repo and safe.
* Stage the study-side changes and commit them once the sweep has finished.

The same applies to `datalad save` and anything else that creates a commit.

## /dev/shm is 63 MB on this host — SpikeInterface will SIGBUS

SpikeInterface allocates waveform buffers in POSIX shared memory by default,
and `format="memory"` does the same. This container ships a 63 MB
`/dev/shm`, so the allocation succeeds and the first touch past the limit
kills the process with **SIGBUS — exit 135, no traceback, no catchable
Python exception**. It looks like a mysterious silent crash and sends you
looking at your own code.

Build analyzers on disk instead:

    from spikeinterface import create_sorting_analyzer
    create_sorting_analyzer(sorting, recording, sparse=...,
                            format="binary_folder", folder=...)

`compbench.metrics.sorting._analyzer_on_disk()` does this; use it rather
than calling `create_sorting_analyzer` directly. Verified: `format="memory"`
exits 135, `format="binary_folder"` exits 0 on the same input.

## numcodecs rejects buffers over 1.97 GiB — chunk accordingly

`numcodecs` raises `ValueError: Codec does not support buffers of >
2113929216 bytes` for a single buffer. A full NP1 recording is ~30 GiB, so
**whole-buffer compression is impossible** for every numcodecs-based codec
(blosc-*, wavpack, lzma, zstd, gzip, zlib, flac). Only T.261 escapes it, by
shelling out to BWC with files rather than passing a buffer.

At 384 ch × 30 kHz × int16 the ceiling is a **92 s** chunk. Useful sizes:

    chunk | buffer   | T.261 subprocess spawns per 1400 s cell
    ----- | -------- | ---------------------------------------
      1 s | 0.02 GiB | 1400   (prohibitive for T.261)
     10 s | 0.21 GiB |  140
     60 s | 1.29 GiB |   23   (the working compromise)
     90 s | 1.93 GiB |   15   (no headroom)

When a profile compares T.261 against numcodecs codecs, both arms must use
the same chunk size or the comparison is between two different measurement
conditions. 60 s satisfies both constraints at once.
