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
    "--fail-on-lossless-mismatch/--no-fail-on-lossless-mismatch",
    default=True,
    help="Exit non-zero if the codec is declared lossless but round-trip is not byte-exact.",
)
def run(
    input_spec: str,
    codec_name: str,
    codec_params: str,
    output_dir: str,
    fail_on_lossless_mismatch: bool,
) -> None:
    """Encode + decode + eval one input with one codec configuration."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    result = run_cell(
        spec=input_spec,
        codec_name=codec_name,
        codec_params=_parse_codec_params(codec_params),
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
