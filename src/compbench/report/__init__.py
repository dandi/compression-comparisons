"""Result aggregation — join per-cell `metrics.json` + `manifest.json`
with the con-duct `<prefix>info.json` in the same directory into a flat
Parquet (or in-memory) table.

`duct` writes a fixed set of files under `--output-prefix`; we look for
`<prefix>info.json` next to each `metrics.json`. Missing con-duct files
just leave the resource columns null — useful when a user ran `compbench`
directly without `duct` wrapping.
"""

from __future__ import annotations

from compbench.report.aggregate import (
    aggregate_directory,
    load_cell,
    load_duct_info,
    write_parquet,
)

__all__ = ["aggregate_directory", "load_cell", "load_duct_info", "write_parquet"]
