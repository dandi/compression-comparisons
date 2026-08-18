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


if __name__ == "__main__":
    main()
