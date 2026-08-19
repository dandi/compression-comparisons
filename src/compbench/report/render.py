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

    table = [
        "| codec | params | CR | enc xRT | dec xRT | RMSE | lossless | wall_s | RSS GB |",
        "| --- | --- | ---: | ---: | ---: | ---: | :---: | ---: | ---: |",
    ]
    for r in rows_list:
        codec = str(r.get("codec_name", "—"))
        disc = _discriminator(r.get("cell_dir"))
        cr = _fmt_num(r.get("metric_cr"))
        enc = _fmt_num(r.get("metric_encode_xrt"), 2)
        dec = _fmt_num(r.get("metric_decode_xrt"), 2)
        rmse = _fmt_num(r.get("metric_rmse"), 4)
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
            f"| {codec} | {disc} | {cr} | {enc} | {dec} | {rmse} | {lossless_cell} | {wall} | {rss_gb} |"
        )

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


def render_from_parquet(
    parquet_path: Path,
    output_path: Path,
    title: str = "Compression benchmark results",
    source_note: str = "",
) -> None:
    rows = _rows_from_parquet(parquet_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_markdown(rows, title=title, source_note=source_note))
