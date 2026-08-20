#!/usr/bin/env python
"""Derive our paper-comparison reference table from the Code Ocean capsule.

The capsule's `data/` asset is CC0 1.0, so the derived table below can live
in this repo. Run this once after unpacking the capsule; the output is
committed so the benchmark can diff against the paper without anyone
needing the capsule.

    python scripts/extract_paper_reference.py \
        --capsule src/capsule-ephys-compression-results \
        --capsule-version v2 \
        --output .specify/specs/paper-reference-lossless.csv

The capsule has two published versions and they are different
manuscripts: v1 (2023-05-22) is the bioRxiv preprint, v2 (2023-08-30) is
the published J. Neural Eng. article. Pass the right one — a number that
"moved" may simply be a revision.

The aggregation deliberately mirrors `code/lossless.ipynb` rather than
inventing our own: median and std over sessions, grouped by every
condition that the notebook ever filters on. Keeping the conditions as
columns — instead of baking in the notebook's headline filter — means a
future comparison against a different figure does not need this script
re-run.
"""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

import pandas as pd

CSV_IN_ZIP = "data/ephys-compression-results/results-lossless/benchmark-lossless.csv"
PROBE_NAMES = {"Neuropixels1.0": "NP1", "Neuropixels2.0": "NP2"}
CONDITIONS = [
    "probe",
    "compressor",
    "level",
    "shuffle",
    "chunk_duration",
    "lsb_mode",
    "channel_chunk_size",
]


def load(capsule: Path) -> pd.DataFrame:
    if capsule.is_dir():
        return pd.read_csv(capsule / CSV_IN_ZIP, index_col=False)
    with zipfile.ZipFile(capsule) as z, z.open(CSV_IN_ZIP) as f:
        return pd.read_csv(f, index_col=False)


def build(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["probe"] = df["probe"].map(PROBE_NAMES).fillna(df["probe"])
    # The capsule's `lsb` column has three values, and the notebook's headline
    # filter is `lsb != 'false'`. That is NOT two-valued: 'true' means an
    # Open Ephys recording that WAS corrected, while 'none' means a SpikeGLX
    # recording with no LSB inflation to correct. Both belong to the
    # corrected condition, and the paper's median-of-8 for NP1 pools four of
    # each. Grouping on the raw column would split that median in half.
    df["lsb_mode"] = (
        df["lsb"].astype(str).map(lambda v: "uncorrected" if v == "false" else "corrected")
    )
    grouped = df.groupby(CONDITIONS, dropna=False)
    out = grouped.agg(
        cr_median=("CR", "median"),
        cr_std=("CR", "std"),
        cr_min=("CR", "min"),
        cr_max=("CR", "max"),
        n_sessions=("session", "nunique"),
        n_rows=("CR", "size"),
        cspeed_xrt_median=("cspeed_xrt", "median"),
        dspeed10s_xrt_median=("dspeed10s_xrt", "median"),
    ).reset_index()
    for col in ("cr_median", "cr_std", "cr_min", "cr_max"):
        out[col] = out[col].round(4)
    for col in ("cspeed_xrt_median", "dspeed10s_xrt_median"):
        out[col] = out[col].round(3)
    return out.sort_values(CONDITIONS).reset_index(drop=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--capsule", type=Path, required=True, help="capsule .zip or unpacked dir")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument(
        "--capsule-version",
        default="v2",
        help="Which published capsule version this data came from (default: v2, "
        "the version matching the published J. Neural Eng. article).",
    )
    args = ap.parse_args()

    table = build(load(args.capsule))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "# Derived from the Code Ocean capsule data asset for Buccino et al. 2023\n"
        "# (doi:10.1088/1741-2552/acf5a4). Source data is CC0 1.0.\n"
        f"# Capsule version: {args.capsule_version}. v2 (2023-08-30) is the\n"
        "# published article; v1 (2023-05-22) is the bioRxiv preprint. These\n"
        "# are different manuscripts, so the version matters.\n"
        "# Regenerate with scripts/extract_paper_reference.py — do not hand-edit.\n"
        "# Aggregation mirrors the capsule's code/lossless.ipynb: median/std over\n"
        "# sessions, with every filterable condition kept as a column.\n"
        + table.to_csv(index=False)
    )
    print(f"wrote {len(table)} rows to {args.output}")


if __name__ == "__main__":
    main()
