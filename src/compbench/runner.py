"""Encode/decode/eval executor — the one-cell primitive under the CLI."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from compbench import codecs, datasets, metrics
from compbench.codecs.base import CodecAdapter
from compbench.datasets.base import LoadedDataset
from compbench.manifest import build_manifest


@dataclass
class CellResult:
    """Everything one benchmark cell produces (excluding con-duct's .jsonl)."""

    manifest: dict[str, Any]
    metrics: dict[str, Any]
    reconstructed: np.ndarray | None = None
    encoded: list[bytes] | None = None


def _resolve_codec(name: str, params: dict[str, Any]) -> CodecAdapter:
    cls = codecs.get(name)
    return cls(**params)


def chunk_bounds(n_samples: int, chunk_samples: int | None) -> list[tuple[int, int]]:
    """Half-open [start, stop) row ranges for one cell's chunking.

    ``None`` (or a chunk at least as long as the recording) means a single
    chunk spanning everything — the historical behaviour.
    """
    if chunk_samples is None or chunk_samples <= 0 or chunk_samples >= n_samples:
        return [(0, n_samples)]
    return [(s, min(s + chunk_samples, n_samples)) for s in range(0, n_samples, chunk_samples)]


def encode(
    dataset: LoadedDataset,
    adapter: CodecAdapter,
    chunk_samples: int | None = None,
) -> tuple[list[bytes], float]:
    """Return (per-chunk encoded buffers, wall-clock encode time in seconds).

    Chunking matters for comparability, not just for streaming: Buccino et
    al. compress through a Zarr store whose chunks are
    (chunk_samples, n_channels), and every headline figure is at a 1 s
    chunk (plan §4.6b(b)). Compressing a whole 60 s buffer in one shot
    gives a codec far more context and a correspondingly better ratio, so
    the two conditions are not comparable.

    Returns a list even in the single-chunk case so callers have one shape
    to handle; CR is then `original_bytes / sum(map(len, buffers))`.
    """
    data = dataset.data
    bounds = chunk_bounds(data.shape[0], chunk_samples)
    t0 = time.perf_counter()
    # `encode_chunk` runs the adapter's filter chain then the compressor,
    # mirroring Zarr's per-chunk pipeline (see CodecAdapter).
    out = [adapter.encode_chunk(np.ascontiguousarray(data[a:b])) for a, b in bounds]
    dt = time.perf_counter() - t0
    return out, dt


def decode(
    encoded: list[bytes],
    adapter: CodecAdapter,
    template: np.ndarray,
    chunk_samples: int | None = None,
) -> tuple[np.ndarray, float]:
    """Decode per-chunk buffers back into one array shaped like `template`.

    numcodecs codecs return raw bytes-like data with no shape/dtype metadata.
    We use the template to reinterpret. `tobytes()` avoids alignment issues
    that `.view(dtype)` can trip on when the codec returns a uint8 array.
    """
    bounds = chunk_bounds(template.shape[0], chunk_samples)
    if len(bounds) != len(encoded):
        raise ValueError(
            f"chunk count mismatch: {len(encoded)} encoded buffer(s) but "
            f"{len(bounds)} chunk bound(s) — encode/decode disagree on chunking"
        )
    n_cols = template.shape[1] if template.ndim > 1 else 1
    out = np.empty(template.shape, dtype=template.dtype)
    flat = out[:, None] if out.ndim == 1 else out
    t0 = time.perf_counter()
    for buf, (a, b) in zip(encoded, bounds, strict=True):
        chunk_template = np.empty((b - a, n_cols), dtype=template.dtype)
        flat[a:b] = adapter.decode_chunk(buf, chunk_template)
    dt = time.perf_counter() - t0
    return out, dt


def run_cell(
    spec: str | Path,
    codec_name: str,
    codec_params: dict[str, Any] | None = None,
    keep_reconstructed: bool = False,
    chunk_duration_s: float | str | None = None,
) -> CellResult:
    """One-shot encode + decode + eval on a single input.

    Metrics returned:
    - `cr`                       compression ratio (original / encoded bytes)
    - `encoded_bytes`
    - `original_bytes`
    - `encode_time_s`, `decode_time_s`
    - `encode_xrt`, `decode_xrt` (duration_s / time_s) — real-time multiples
    - `rmse`
    - `round_trip_ok`            True iff byte-exact match

    Note: `encode_xrt`/`decode_xrt` come from Python-side `perf_counter`. The
    orchestrator's con-duct wrapping provides the authoritative wall time —
    prefer that at aggregation time. These are provided for a quick sanity
    check without needing con-duct.
    """
    codec_params = codec_params or {}
    ds = datasets.load(spec)
    adapter = _resolve_codec(codec_name, codec_params)

    # CLI and YAML both hand this in as a string; "None"/"" mean "unset".
    chunk_s: float | None = (
        None if chunk_duration_s in (None, "None", "") else float(chunk_duration_s)
    )
    chunk_samples = None if chunk_s is None else max(1, round(chunk_s * ds.sample_rate_hz))
    encoded, enc_dt = encode(ds, adapter, chunk_samples=chunk_samples)
    reconstructed, dec_dt = decode(encoded, adapter, template=ds.data, chunk_samples=chunk_samples)

    n_chunks = len(encoded)
    encoded_bytes = sum(len(b) for b in encoded)
    cr = metrics.compression_ratio(ds.nbytes, encoded_bytes)
    if not keep_reconstructed:
        # The encoded buffer is dead once its length is recorded, but it is
        # the compressed image of a 27 GB input — several GB that would
        # otherwise sit alongside the metric pass (plan §Phase 3.5 [R5-H2]).
        del encoded
        encoded = []
    exact = metrics.round_trip_ok(ds.data, reconstructed)

    # Every distortion statistic comes from one bounded-memory pass. The
    # previous approach promoted both arrays to float64 up front, which at
    # the paper's 1200 s recordings is 220 GB of float64 before filtfilt's
    # own temporaries — see `metrics.distortion_summary`.
    if exact:
        # Lossless round-trip → every distortion metric is analytically zero;
        # skip the multi-second filtfilt / dot-product ceremony. This alone
        # saves ~20s/cell for the majority of paper-comparable cells.
        err = 0.0
        prd_val = 0.0
        prdn_val = 0.0
        band_rmse: float | None = 0.0 if ds.sample_rate_hz > 12000.0 else None
        signal_std = metrics.signal_std(ds.data)
        prdn_median: float | None = 0.0
        prdn_iqr: float | None = 0.0
        prdn_max: float | None = 0.0
    else:
        dist = metrics.distortion_summary(ds.data, reconstructed, ds.sample_rate_hz, 300.0, 6000.0)
        err = dist["rmse"]
        prd_val = dist["prd_percent"]
        prdn_val = dist["prdn_percent"]
        signal_std = dist["signal_std"]
        band_rmse = dist["rmse_band_limited"]
        prdn_median = dist["prdn_per_channel_median_percent"]
        prdn_iqr = dist["prdn_per_channel_iqr_percent"]
        prdn_max = dist["prdn_per_channel_max_percent"]

    duration = ds.duration_s
    result_metrics = {
        "cr": cr,
        "original_bytes": ds.nbytes,
        "encoded_bytes": encoded_bytes,
        # Chunking is a comparability axis, not a detail — the paper's
        # headline figures are all at 1 s chunks (plan §4.6b(b)).
        "chunk_duration_s": chunk_s,
        "n_chunks": n_chunks,
        "encode_time_s": enc_dt,
        "decode_time_s": dec_dt,
        "encode_xrt": (duration / enc_dt) if enc_dt > 0 else None,
        "decode_xrt": (duration / dec_dt) if dec_dt > 0 else None,
        "rmse": err,
        "rmse_band_limited_300_6000": band_rmse,
        "prd_percent": prd_val,
        "prdn_percent": prdn_val,
        # Pooled PRDN normalises by the std across *all* channels, which on a
        # 384-channel probe is dominated by the loudest ones and understates
        # what a typical channel sees. The per-channel median is the
        # reader-facing number (plan §Phase 3.5 [R1-H2]).
        "prdn_per_channel_median_percent": prdn_median,
        "prdn_per_channel_iqr_percent": prdn_iqr,
        "prdn_per_channel_max_percent": prdn_max,
        "signal_std": signal_std,
        "rmse_over_signal_std_percent": (100.0 * err / signal_std) if signal_std > 0 else 0.0,
        "round_trip_ok": exact,
        "expected_lossless": not adapter.lossy,
        # Correctness alarm: declared-lossless codec produced non-exact output.
        # (Round-2 R4-REG1 fixed inverted logic here.)
        "lossless_violation": (not adapter.lossy) and (not exact),
    }

    manifest = build_manifest(
        dataset_provenance=ds.provenance,
        codec_description=adapter.describe(),
        input_array=ds.data,
        sample_rate_hz=ds.sample_rate_hz,
        duration_s=duration,
    )
    return CellResult(
        manifest=manifest,
        metrics=result_metrics,
        reconstructed=reconstructed if keep_reconstructed else None,
        encoded=encoded if keep_reconstructed else None,
    )
