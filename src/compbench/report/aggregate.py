"""Join per-cell compbench outputs with con-duct resource logs → tabular rows."""

from __future__ import annotations

import json
import warnings
from collections.abc import Iterator
from pathlib import Path
from typing import Any

_DUCT_INFO_SUFFIX = "info.json"


class AmbiguousDuctInfoWarning(UserWarning):
    """Multiple `*info.json` candidates in a cell dir → resource fields dropped."""


def _find_duct_info(cell_dir: Path) -> Path | None:
    """Locate `<prefix>info.json` alongside `metrics.json`.

    Convention: Snakemake / user invokes `duct --output-prefix <cell_dir>/duct- …`,
    so the file is `<cell_dir>/duct-info.json`. We also accept any single
    `*info.json` in the directory as a fallback.

    On ambiguity (multiple non-standard `*info.json` files, none named
    `duct-info.json`) we emit an :class:`AmbiguousDuctInfoWarning` — the row
    will lack `duct_*` fields and a silent null is misleading.
    """
    candidate = cell_dir / f"duct-{_DUCT_INFO_SUFFIX}"
    if candidate.exists():
        return candidate
    matches = sorted(cell_dir.glob(f"*{_DUCT_INFO_SUFFIX}"))
    # Exclude our own manifest.json / metrics.json which happen to share the suffix.
    matches = [p for p in matches if p.name not in {"manifest.json", "metrics.json"}]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        warnings.warn(
            f"Ambiguous duct-info in {cell_dir}: {[p.name for p in matches]}. "
            "Resource fields will be null. Use --output-prefix duct- for a "
            "single canonical file.",
            AmbiguousDuctInfoWarning,
            stacklevel=2,
        )
    return None


def load_duct_info(path: Path) -> dict[str, Any]:
    """Extract the fields we care about from a duct `<prefix>info.json`."""
    with path.open() as f:
        blob = json.load(f)
    summary = blob.get("execution_summary", {})
    return {
        "duct_wall_time_s": summary.get("wall_clock_time"),
        "duct_peak_rss_bytes": summary.get("peak_rss"),
        "duct_average_rss_bytes": summary.get("average_rss"),
        "duct_peak_vsz_bytes": summary.get("peak_vsz"),
        "duct_average_vsz_bytes": summary.get("average_vsz"),
        "duct_peak_pcpu": summary.get("peak_pcpu"),
        "duct_average_pcpu": summary.get("average_pcpu"),
        "duct_exit_code": summary.get("exit_code"),
        "duct_num_samples": summary.get("num_samples"),
        "duct_start_time": summary.get("start_time"),
        "duct_end_time": summary.get("end_time"),
    }


def _preprocessing_summary(manifest: dict[str, Any]) -> str:
    """One-line rendering of the preprocessing chain, e.g. `bandpass(300-6000Hz,o4)`.

    Returns "raw" when no preprocessing was applied, so the column is never
    null and `df.groupby("preprocessing_summary")` always partitions cleanly.
    """
    steps = manifest.get("input", {}).get("provenance", {}).get("preprocessing") or []
    if not steps:
        return "raw"
    parts: list[str] = []
    for step in steps:
        if not isinstance(step, dict):
            parts.append(str(step))
            continue
        kind = step.get("kind", "?")
        if kind == "lsb_correction":
            parts.append(f"lsb{step.get('lsb', '?')}")
            continue
        if kind == "bandpass":
            parts.append(
                f"bandpass({step.get('low_hz', '?')}-{step.get('high_hz', '?')}Hz"
                f",o{step.get('order', '?')})"
            )
        else:
            args = ",".join(f"{k}={v}" for k, v in step.items() if k != "kind")
            parts.append(f"{kind}({args})" if args else str(kind))
    return "+".join(parts)


def load_cell(cell_dir: Path) -> dict[str, Any] | None:
    """Assemble one row from a directory containing at least `metrics.json`.

    Returns None if `metrics.json` is missing (i.e. this dir is not a cell).
    """
    metrics_path = cell_dir / "metrics.json"
    manifest_path = cell_dir / "manifest.json"
    if not metrics_path.exists():
        return None
    with metrics_path.open() as f:
        metrics = json.load(f)
    manifest: dict[str, Any] = {}
    if manifest_path.exists():
        with manifest_path.open() as f:
            manifest = json.load(f)

    row: dict[str, Any] = {
        "cell_dir": str(cell_dir),
        # Metrics (correctness)
        **{f"metric_{k}": v for k, v in metrics.items()},
        # Manifest — flat top-level, plus a few frequently-queried inner fields
        "codec_name": manifest.get("codec", {}).get("name"),
        "codec_lossy": manifest.get("codec", {}).get("lossy"),
        "input_nbytes": manifest.get("input", {}).get("nbytes"),
        "input_duration_s": manifest.get("input", {}).get("duration_s"),
        "input_sample_rate_hz": manifest.get("input", {}).get("sample_rate_hz"),
        "input_n_channels": manifest.get("input", {}).get("n_channels"),
        "input_dtype": manifest.get("input", {}).get("dtype"),
        "input_sha256": manifest.get("input", {}).get("sha256"),
        # Raw vs band-pass is the difference between reproducing the paper's
        # Fig 2 and its Fig 7. Without this column a reader has to open each
        # cell's manifest.json to tell them apart (plan §Phase 3.5 [R2-H3]).
        "preprocessing_summary": _preprocessing_summary(manifest),
        "dataset_loader": manifest.get("input", {}).get("provenance", {}).get("loader"),
        "dataset_yaml_source": manifest.get("input", {}).get("provenance", {}).get("yaml_source"),
        # git-annex key of the source recording — distinguishes two runs
        # against the same path at different data versions ([R2-H2]).
        "input_annex_key": manifest.get("input", {})
        .get("provenance", {})
        .get("source", {})
        .get("annex_key"),
        "input_dataset_commit": manifest.get("input", {})
        .get("provenance", {})
        .get("source", {})
        .get("dataset_commit"),
        "compbench_version": manifest.get("compbench_version"),
        "git_sha": manifest.get("git_sha"),
        "created_utc": manifest.get("created_utc"),
    }

    duct_info = _find_duct_info(cell_dir)
    if duct_info is not None:
        row.update(load_duct_info(duct_info))
        row["duct_info_path"] = str(duct_info)
        # Derived: xRT from con-duct wall time — this is the authoritative measure.
        wall = row.get("duct_wall_time_s")
        duration = row.get("input_duration_s")
        if wall and duration and wall > 0:
            row["derived_xrt_duct"] = duration / wall

    return row


def _iter_cell_dirs(root: Path) -> Iterator[Path]:
    """Yield every directory under `root` (inclusive) that contains `metrics.json`."""
    if (root / "metrics.json").exists():
        yield root
    yield from (p.parent for p in root.rglob("metrics.json") if p.parent != root)


def aggregate_directory(root: Path) -> list[dict[str, Any]]:
    """Walk `root` and return one row per cell."""
    rows: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for cell_dir in _iter_cell_dirs(root):
        if cell_dir in seen:
            continue
        seen.add(cell_dir)
        row = load_cell(cell_dir)
        if row is not None:
            rows.append(row)
    return rows


def write_parquet(rows: list[dict[str, Any]], output: Path) -> None:
    """Write rows to a Parquet file. Requires `pyarrow`."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    output.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        # Write an empty table with no columns so downstream can still read it.
        pq.write_table(pa.table({}), output)
        return
    # Pad missing keys with None so the table has a uniform column set.
    all_keys: set[str] = set()
    for r in rows:
        all_keys.update(r)
    padded = [{k: r.get(k) for k in all_keys} for r in rows]
    pq.write_table(pa.Table.from_pylist(padded), output)
