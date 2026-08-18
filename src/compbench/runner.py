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
    encoded: bytes | None = None


def _resolve_codec(name: str, params: dict[str, Any]) -> CodecAdapter:
    cls = codecs.get(name)
    return cls(**params)


def encode(dataset: LoadedDataset, adapter: CodecAdapter) -> tuple[bytes, float]:
    """Return (encoded bytes, wall-clock encode time in seconds)."""
    codec = adapter.make_codec()
    t0 = time.perf_counter()
    encoded = codec.encode(dataset.data)
    dt = time.perf_counter() - t0
    return bytes(encoded), dt


def decode(encoded: bytes, adapter: CodecAdapter, template: np.ndarray) -> tuple[np.ndarray, float]:
    """Decode into a numpy array with `template`'s dtype and shape.

    numcodecs codecs return raw bytes-like data with no shape/dtype metadata.
    We use the template to reinterpret. `tobytes()` avoids alignment issues
    that `.view(dtype)` can trip on when the codec returns a uint8 array.
    """
    codec = adapter.make_codec()
    t0 = time.perf_counter()
    raw = codec.decode(encoded)
    raw_bytes = raw.tobytes() if isinstance(raw, np.ndarray) else bytes(raw)
    out = np.frombuffer(raw_bytes, dtype=template.dtype).reshape(template.shape)
    dt = time.perf_counter() - t0
    return out, dt


def run_cell(
    spec: str | Path,
    codec_name: str,
    codec_params: dict[str, Any] | None = None,
    keep_reconstructed: bool = False,
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

    encoded, enc_dt = encode(ds, adapter)
    reconstructed, dec_dt = decode(encoded, adapter, template=ds.data)

    cr = metrics.compression_ratio(ds.nbytes, len(encoded))
    err = metrics.rmse(ds.data, reconstructed)
    exact = metrics.round_trip_ok(ds.data, reconstructed)

    duration = ds.duration_s
    result_metrics = {
        "cr": cr,
        "original_bytes": ds.nbytes,
        "encoded_bytes": len(encoded),
        "encode_time_s": enc_dt,
        "decode_time_s": dec_dt,
        "encode_xrt": (duration / enc_dt) if enc_dt > 0 else None,
        "decode_xrt": (duration / dec_dt) if dec_dt > 0 else None,
        "rmse": err,
        "round_trip_ok": exact,
        "expected_lossless": not adapter.lossy,
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
