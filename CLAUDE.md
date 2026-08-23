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
