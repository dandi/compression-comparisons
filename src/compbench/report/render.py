"""Render a report.parquet as a Markdown results document.

Idempotent: rerun after any new cells land and the table updates automatically.
The Markdown is intentionally plain (no plotting deps) so it renders on
GitHub, GitLab, and inside a text editor without extra tooling.

Called via ``compbench render-report`` (CLI subcommand) or directly with
``python -m compbench.report.render``.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any


def _rows_from_parquet(path: Path) -> list[dict[str, Any]]:
    import pyarrow.parquet as pq

    tab = pq.read_table(path)
    d = tab.to_pydict()
    n = tab.num_rows
    return [{k: d[k][i] for k in d} for i in range(n)]


def _fmt_num(v: Any, precision: int = 3) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "T" if v else "F"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if v != v:  # NaN
            return "—"
        return f"{v:.{precision}f}"
    return str(v)


def _discriminator(cell_dir: Any) -> str:
    if not cell_dir:
        return ""
    tag = str(cell_dir).rstrip("/").split("/")[-1]
    if "__" in tag:
        tag = tag.split("__", 1)[1]
    return tag


def _dataset_of(cell_dir: Any) -> str:
    """Dataset half of the `<dataset>__<codec>` cell-directory name."""
    if not cell_dir:
        return "—"
    tag = str(cell_dir).rstrip("/").split("/")[-1]
    return tag.split("__", 1)[0] if "__" in tag else tag


def _preproc_of(row: dict[str, Any]) -> str:
    """Preprocessing label, falling back to `raw` for pre-[R2-H3] derivatives."""
    v = row.get("preprocessing_summary")
    return str(v) if v else "raw"


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return 0.5 * (ordered[mid - 1] + ordered[mid])


def _cr_of(row: dict[str, Any]) -> float:
    """Extract the CR field as a float for sorting; missing → -inf."""
    v = row.get("metric_cr")
    return float(v) if isinstance(v, (int, float)) else float("-inf")


def render_markdown(
    rows: Iterable[dict[str, Any]],
    title: str = "Compression benchmark results",
    source_note: str = "",
) -> str:
    """Return the Markdown document body."""
    rows_list = list(rows)
    # Sort by CR descending; unknown CR to the bottom.
    rows_list.sort(key=lambda r: -_cr_of(r))

    n = len(rows_list)
    lossless_n = sum(1 for r in rows_list if r.get("codec_lossy") is False)
    lossy_n = sum(1 for r in rows_list if r.get("codec_lossy") is True)

    header = [
        f"# {title}",
        "",
        f"**Cells:** {n} total ({lossless_n} lossless + {lossy_n} lossy).",
    ]
    if source_note:
        header.extend(["", source_note])
    header.append("")

    # `dataset` and `preproc` matter once a sweep spans more than one
    # recording: without them every row of a 448-cell paper sweep looks
    # identical apart from the codec params. `RMSE_bp` is the spike-band
    # error (paper Fig 4-6 methodology) and `PRDN/ch` is the per-channel
    # median — the reader-facing distortion figure per plan [R1-H2].
    table = [
        "| dataset | preproc | codec | params | CR | enc xRT | dec xRT | RMSE | "
        "RMSE_bp | PRDN/ch % | lossless | wall_s | RSS GB |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | :---: | ---: | ---: |",
    ]
    for r in rows_list:
        dataset = _dataset_of(r.get("cell_dir"))
        preproc = _preproc_of(r)
        codec = str(r.get("codec_name", "—"))
        disc = _discriminator(r.get("cell_dir"))
        cr = _fmt_num(r.get("metric_cr"))
        enc = _fmt_num(r.get("metric_encode_xrt"), 2)
        dec = _fmt_num(r.get("metric_decode_xrt"), 2)
        rmse = _fmt_num(r.get("metric_rmse"), 4)
        rmse_bp = _fmt_num(r.get("metric_rmse_band_limited_300_6000"), 4)
        prdn_ch = _fmt_num(r.get("metric_prdn_per_channel_median_percent"), 2)
        ok_val = r.get("metric_round_trip_ok")
        lossless_cell = "T" if ok_val else "F" if ok_val is False else "—"
        wall = _fmt_num(r.get("duct_wall_time_s"), 2)
        rss_bytes = r.get("duct_peak_rss_bytes")
        rss_gb = (
            _fmt_num(rss_bytes / 1024**3, 2)
            if isinstance(rss_bytes, (int, float)) and rss_bytes
            else "—"
        )
        table.append(
            f"| {dataset} | {preproc} | {codec} | {disc} | {cr} | {enc} | {dec} | "
            f"{rmse} | {rmse_bp} | {prdn_ch} | {lossless_cell} | {wall} | {rss_gb} |"
        )
    table.extend(_median_section(rows_list))

    # Best lossless / best lossy highlight
    best_lossless: dict[str, Any] | None = None
    best_lossy: dict[str, Any] | None = None
    for r in rows_list:
        if _cr_of(r) == float("-inf"):
            continue
        if r.get("codec_lossy") is False and (
            best_lossless is None or _cr_of(r) > _cr_of(best_lossless)
        ):
            best_lossless = r
        elif r.get("codec_lossy") is True and (
            best_lossy is None or _cr_of(r) > _cr_of(best_lossy)
        ):
            best_lossy = r

    highlights: list[str] = ["", "## Highlights", ""]
    if best_lossless is not None:
        highlights.append(
            f"- **Best lossless:** `{best_lossless.get('codec_name')}` "
            f"({_discriminator(best_lossless.get('cell_dir'))}) — CR "
            f"{_fmt_num(best_lossless.get('metric_cr'))}."
        )
    if best_lossy is not None:
        highlights.append(
            f"- **Best lossy CR:** `{best_lossy.get('codec_name')}` "
            f"({_discriminator(best_lossy.get('cell_dir'))}) — CR "
            f"{_fmt_num(best_lossy.get('metric_cr'))}, "
            f"RMSE {_fmt_num(best_lossy.get('metric_rmse'), 4)}."
        )
    if best_lossless is None and best_lossy is None:
        highlights.append("- (no cells with a comparable CR field)")

    return "\n".join(header + table + highlights) + "\n"


def _median_section(rows_list: list[dict[str, Any]]) -> list[str]:
    """Per-(preprocessing, codec, params) median CR across datasets.

    This is the shape the Phase 1 gate is stated in (plan §5): the paper
    reports a distribution over 8 NP1 recordings, so the comparable figure
    from our sweep is the median across recordings, not any single cell.
    Emitted only when the sweep actually spans more than one dataset —
    on a single-recording sweep the median is just the row itself.
    """
    datasets = {_dataset_of(r.get("cell_dir")) for r in rows_list}
    if len(datasets) < 2:
        return []

    groups: dict[tuple[str, str, str], list[float]] = {}
    for r in rows_list:
        cr = _cr_of(r)
        if cr == float("-inf"):
            continue
        key = (
            _preproc_of(r),
            str(r.get("codec_name", "—")),
            _discriminator(r.get("cell_dir")),
        )
        groups.setdefault(key, []).append(cr)

    out = [
        "",
        f"## Median CR across {len(datasets)} datasets",
        "",
        "The paper reports distributions over its recording set; this is the "
        "comparable per-codec figure. `n` is the number of datasets "
        "contributing — a short `n` means cells are still missing or failed.",
        "",
        "| preproc | codec | params | median CR | min | max | n |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    # Sort by preprocessing, then median CR descending — stable across runs.
    for (preproc, codec, params), crs in sorted(
        groups.items(), key=lambda kv: (kv[0][0], -_median(kv[1]), kv[0][1], kv[0][2])
    ):
        out.append(
            f"| {preproc} | {codec} | {params} | {_fmt_num(_median(crs))} | "
            f"{_fmt_num(min(crs))} | {_fmt_num(max(crs))} | {len(crs)} |"
        )
    return out


def render_from_parquet(
    parquet_path: Path,
    output_path: Path,
    title: str = "Compression benchmark results",
    source_note: str = "",
) -> None:
    rows = _rows_from_parquet(parquet_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_markdown(rows, title=title, source_note=source_note))
