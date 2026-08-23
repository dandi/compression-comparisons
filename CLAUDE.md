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
