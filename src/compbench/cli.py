"""`compbench` CLI — the reusable primitive.

One invocation = one benchmark cell. No orchestration, no sweep enumeration.
Snakemake or a shell loop is expected to wrap this via ``duct compbench …``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import click

from compbench import __version__, codecs
from compbench.report import aggregate_directory, render_from_parquet, write_parquet
from compbench.runner import run_cell


def _parse_codec_params(raw: str | None) -> dict[str, Any]:
    """Parse ``k=v,k=v`` — values kept as strings for the adapter to coerce."""
    if not raw:
        return {}
    out: dict[str, Any] = {}
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" not in chunk:
            raise click.BadParameter(f"expected k=v, got {chunk!r}")
        k, _, v = chunk.partition("=")
        out[k.strip()] = v.strip()
    return out


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="compbench")
def main() -> None:
    """Compression benchmark primitive."""


@main.command("list-codecs")
def list_codecs() -> None:
    """Print registered codec names, one per line."""
    for name in codecs.names():
        click.echo(name)


@main.command("describe-codec")
@click.argument("name")
def describe_codec(name: str) -> None:
    """Print a codec adapter's default parameter description (JSON)."""
    try:
        cls = codecs.get(name)
    except KeyError as e:
        raise click.ClickException(str(e)) from None
    adapter = cls()
    click.echo(json.dumps(adapter.describe(), indent=2, sort_keys=True))


@main.command("run")
@click.option(
    "--input",
    "input_spec",
    required=True,
    help="Dataset spec: `synthetic:k=v,...`, path/to/data.npy, or path/to/dataset.yaml",
)
@click.option("--codec", "codec_name", required=True, help="Registered codec name.")
@click.option(
    "--codec-params",
    default="",
    help="k=v,k=v parameters forwarded to the codec adapter.",
)
@click.option(
    "--output-dir",
    "output_dir",
    required=True,
    type=click.Path(file_okay=False),
    help="Output directory; will be created if missing.",
)
@click.option(
    "--chunk-duration-s",
    "chunk_duration_s",
    default=None,
    type=float,
    help=(
        "Compress in chunks of this many seconds instead of one whole-buffer "
        "chunk. Buccino et al.'s headline figures are all at 1 s; a whole-buffer "
        "chunk gives the codec more context and a better ratio, so the two are "
        "not comparable."
    ),
)
@click.option(
    "--fail-on-lossless-mismatch/--no-fail-on-lossless-mismatch",
    default=True,
    help="Exit non-zero if the codec is declared lossless but round-trip is not byte-exact.",
)
def run(
    input_spec: str,
    codec_name: str,
    codec_params: str,
    output_dir: str,
    chunk_duration_s: float | None,
    fail_on_lossless_mismatch: bool,
) -> None:
    """Encode + decode + eval one input with one codec configuration."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    result = run_cell(
        spec=input_spec,
        codec_name=codec_name,
        codec_params=_parse_codec_params(codec_params),
        chunk_duration_s=chunk_duration_s,
    )

    (out / "manifest.json").write_text(json.dumps(result.manifest, indent=2, sort_keys=True))
    (out / "metrics.json").write_text(json.dumps(result.metrics, indent=2, sort_keys=True))

    click.echo(
        f"cr={result.metrics['cr']:.3f} "
        f"encode_xrt={result.metrics['encode_xrt']:.1f} "
        f"decode_xrt={result.metrics['decode_xrt']:.1f} "
        f"rmse={result.metrics['rmse']:.4g} "
        f"round_trip_ok={result.metrics['round_trip_ok']}"
    )

    if (
        fail_on_lossless_mismatch
        and result.metrics["expected_lossless"]
        and not result.metrics["round_trip_ok"]
    ):
        click.echo("ERROR: lossless codec produced non-exact round-trip.", err=True)
        sys.exit(2)


@main.command("report")
@click.option(
    "--results-dir",
    required=True,
    type=click.Path(exists=True, file_okay=False),
    help="Root directory to walk for per-cell `metrics.json` files.",
)
@click.option(
    "--output",
    required=True,
    type=click.Path(dir_okay=False),
    help="Output path — `.parquet` for Parquet, `.jsonl` for JSON Lines.",
)
def report(results_dir: str, output: str) -> None:
    """Aggregate a directory of benchmark cells into a table."""
    rows = aggregate_directory(Path(results_dir))
    out = Path(output)
    if out.suffix == ".parquet":
        write_parquet(rows, out)
    elif out.suffix == ".jsonl":
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w") as f:
            for row in rows:
                f.write(json.dumps(row, sort_keys=True) + "\n")
    else:
        raise click.ClickException(f"Unsupported --output extension: {out.suffix!r}")
    click.echo(f"wrote {len(rows)} row(s) to {out}")


@main.command("t261-progress")
@click.option(
    "--log",
    "log_path",
    required=False,
    type=click.Path(dir_okay=False),
    help="Encoder stdout log path (e.g. <scratch>/enc-*/encode.stdout.log).",
)
@click.option(
    "--scratch",
    "scratch_root",
    required=False,
    type=click.Path(exists=True, file_okay=False),
    help="Alternative to --log: root of a `progress_dir` scratch tree; picks newest enc-*.",
)
@click.option(
    "--watch",
    "watch_mode",
    is_flag=True,
    help="Poll the log periodically until the process exits.",
)
@click.option(
    "--interval",
    "interval_s",
    default=5.0,
    help="Watch interval seconds (default 5).",
)
@click.option(
    "--expected-segments",
    "expected_segments",
    type=int,
    default=None,
    help="Total segments this encode is expected to emit — derived from a completed reference run. Enables ETA.",
)
def t261_progress(
    log_path: str | None,
    scratch_root: str | None,
    watch_mode: bool,
    interval_s: float,
    expected_segments: int | None,
) -> None:
    """Parse T.261 encoder progress logs to estimate ETA."""
    from compbench.t261_progress import find_active_encode_scratch, parse_log, watch

    if log_path is None:
        if scratch_root is None:
            raise click.UsageError("pass --log <path> or --scratch <root>")
        found = find_active_encode_scratch(scratch_root)
        if found is None:
            raise click.ClickException(f"no enc-*/encode.stdout.log under {scratch_root}")
        log_path = str(found)
    if watch_mode:
        watch(log_path, interval_s=interval_s, expected_total_segments=expected_segments)
        return
    p = Path(log_path)
    start = p.stat().st_mtime if p.exists() else None
    # Best-effort start-time inference: mtime of the first line's write.
    # In practice, the caller should pass through the codec's `progress_dir`
    # timestamp; for a one-shot query we approximate with the file mtime.
    snap = parse_log(log_path, start_epoch=start, expected_total_segments=expected_segments)
    click.echo(snap.human_line())


@main.command("render-report")
@click.option(
    "--parquet",
    "parquet_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Path to the report.parquet produced by `compbench report`.",
)
@click.option(
    "--output",
    "output_path",
    required=True,
    type=click.Path(dir_okay=False),
    help="Where to write the Markdown report (typically RESULTS.md).",
)
@click.option(
    "--title",
    default="Compression benchmark results",
    help="Document H1 title.",
)
@click.option(
    "--source-note",
    default="",
    help="Optional paragraph to insert after the summary line (dataset provenance, etc.).",
)
def render_report(parquet_path: str, output_path: str, title: str, source_note: str) -> None:
    """Regenerate a Markdown results table from a report.parquet.

    Idempotent — rerun after new cells land and the table updates.
    """
    render_from_parquet(
        Path(parquet_path),
        Path(output_path),
        title=title,
        source_note=source_note,
    )
    click.echo(f"wrote {output_path}")


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# Lossy-vs-sorting pipeline (plan §4.6c). Three commands, not one, so that a
# sorter change does not force a recompress and a threshold change does not
# force a re-sort. Each writes a durable artifact the next consumes, which is
# also what makes each one a clean `datalad run` unit.
# ---------------------------------------------------------------------------


@main.command("compress")
@click.option("--mearec", "mearec_path", required=True, type=click.Path(exists=True))
@click.option("--lsb", type=int, default=None, help="LSB to correct (NP1: 12, NP2: 3).")
@click.option("--start-s", type=float, default=0.0)
@click.option("--duration-s", type=float, default=None)
@click.option("--codec", "codec_name", required=True)
@click.option("--codec-params", default="")
@click.option("--chunk-duration-s", type=float, default=1.0)
@click.option("--n-jobs", type=int, default=1)
@click.option("--output-dir", required=True, type=click.Path(file_okay=False))
def compress_cmd(
    mearec_path: str,
    lsb: int | None,
    start_s: float,
    duration_s: float | None,
    codec_name: str,
    codec_params: str,
    chunk_duration_s: float,
    n_jobs: int,
    output_dir: str,
) -> None:
    """Stage 1 — compress a recording to Zarr and measure distortion."""
    from compbench.datasets.mearec import load_recording
    from compbench.sorting_pipeline import compress

    rec, _ = load_recording(mearec_path, start_s=start_s, duration_s=duration_s, lsb=lsb)
    m = compress(
        rec,
        codec_name,
        _parse_codec_params(codec_params),
        Path(output_dir),
        chunk_duration_s=chunk_duration_s,
        n_jobs=n_jobs,
    )
    click.echo(
        f"cr={m['cr']:.3f} rmse_uv={m['rmse_uv']:.4f} "
        f"exact={m['round_trip_exact']} violation={m['lossless_violation']}"
    )
    if m["lossless_violation"]:
        click.echo("ERROR: codec declared lossless but round-trip was not exact.", err=True)
        sys.exit(2)


@main.command("spikesort")
@click.option("--zarr", "zarr_path", required=True, type=click.Path(exists=True))
@click.option("--sorter", default="kilosort4")
@click.option("--output-dir", required=True, type=click.Path(file_okay=False))
@click.option("--n-jobs", type=int, default=1)
@click.option(
    "--common-reference/--no-common-reference",
    default=False,
    help="Paper applies CMR to experimental data only, never to the GT path.",
)
def spikesort_cmd(
    zarr_path: str, sorter: str, output_dir: str, n_jobs: int, common_reference: bool
) -> None:
    """Stage 2 — sort a stored recording."""
    from compbench.sorting_pipeline import spikesort

    info = spikesort(
        Path(zarr_path),
        Path(output_dir),
        sorter=sorter,
        common_reference=common_reference,
        n_jobs=n_jobs,
    )
    click.echo(
        f"sorter={info['sorter']}/{info['sorter_version']} "
        f"units={info['n_units']} spikes={info['n_spikes']} sort_s={info['sort_s']:.1f}"
    )


@main.command("compare-sorting")
@click.option("--sorting", "sorting_path", required=True, type=click.Path(exists=True))
@click.option("--mearec", "mearec_path", required=True, type=click.Path(exists=True))
@click.option("--start-s", type=float, default=0.0)
@click.option("--duration-s", type=float, default=None)
@click.option("--output-dir", required=True, type=click.Path(file_okay=False))
def compare_sorting_cmd(
    sorting_path: str,
    mearec_path: str,
    start_s: float,
    duration_s: float | None,
    output_dir: str,
) -> None:
    """Stage 3 — compare a stored sorting against ground truth."""
    from compbench.datasets.mearec import load_recording
    from compbench.sorting_pipeline import compare_to_ground_truth

    # lsb is irrelevant here: only the ground-truth spike trains are used.
    _, gt = load_recording(mearec_path, start_s=start_s, duration_s=duration_s)
    r = compare_to_ground_truth(Path(sorting_path), gt, Path(output_dir))
    p, c = r["pooled"], r["unit_counts"]
    click.echo(
        f"accuracy={p['accuracy']:.4f} precision={p['precision']:.4f} "
        f"recall={p['recall']:.4f} well_detected={c['num_well_detected']} "
        f"false_positive={c['num_false_positive']}"
    )
