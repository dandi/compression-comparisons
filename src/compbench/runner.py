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
    exact = metrics.round_trip_ok(ds.data, reconstructed)

    # Precompute the float64 promotions once and pass to every metric.
    # Before this consolidation each metric independently promoted `ds.data`
    # to float64 → 4-5x redundant allocation per cell (~1 GB on 230 MB int16
    # input). Now: two arrays, shared across all metrics.
    if exact:
        # Lossless round-trip → every distortion metric is analytically zero;
        # skip the multi-second filtfilt / dot-product ceremony. This alone
        # saves ~20s/cell for the majority of paper-comparable cells.
        err = 0.0
        prd_val = 0.0
        prdn_val = 0.0
        band_rmse: float | None = 0.0 if ds.sample_rate_hz > 12000.0 else None
        signal_std = float(np.std(ds.data.astype(np.float64))) if ds.data.size else 0.0
    else:
        orig64 = ds.data.astype(np.float64)
        recon64 = reconstructed.astype(np.float64)
        err = metrics.rmse(orig64, recon64)
        prd_val = metrics.prd(orig64, recon64)
        prdn_val = metrics.prdn(orig64, recon64)
        signal_std = float(np.std(orig64)) if orig64.size else 0.0
        # Band-limited RMSE (Buccino Fig 4-6 methodology). Nyquist gate:
        # need sample_rate > 2 * high_hz to bandpass at 300-6000 Hz.
        band_rmse = None
        if ds.sample_rate_hz > 12000.0:
            try:
                band_rmse = metrics.rmse_band_limited(
                    orig64, recon64, ds.sample_rate_hz, 300.0, 6000.0
                )
            except ValueError:
                band_rmse = None

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
        "rmse_band_limited_300_6000": band_rmse,
        "prd_percent": prd_val,
        "prdn_percent": prdn_val,
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
