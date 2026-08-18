"""SpikeInterface loader — thin adapter over `si.extractors.read_*`.

Registers the `spikeinterface:` and `si:` scheme. Handles auto-detection based
on file/dir structure, plus explicit `reader=<name>` override for anything
under `spikeinterface.extractors`.

Only imported (and thus registered) if `spikeinterface` is installed.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

import numpy as np

from compbench.datasets import register
from compbench.datasets.base import LoadedDataset

with contextlib.suppress(ImportError):
    import spikeinterface.extractors as _se

_HAVE_SI = "_se" in globals()


def _detect_reader(path: Path) -> str:
    """Guess the SpikeInterface reader from a path."""
    if path.is_dir():
        # OpenEphys directory contains "*.oebin" or "structure.oebin"
        if any(path.rglob("*.oebin")):
            return "openephys"
        # SpikeGLX dirs contain "*.ap.bin" / "*.ap.meta"
        if any(path.rglob("*.ap.bin")) or any(path.rglob("*.ap.meta")):
            return "spikeglx"
        # Zarr directory
        if (path / ".zgroup").exists() or (path / ".zarray").exists():
            return "zarr"
    else:
        suf = path.suffix.lower()
        if suf == ".nwb":
            return "nwb_recording"
        if suf == ".bin" and path.with_suffix(".meta").exists():
            return "spikeglx"
        if suf in {".zarr"}:
            return "zarr"
    raise ValueError(
        f"Cannot auto-detect SpikeInterface reader for {path}. Pass reader=... explicitly."
    )


def _slice_recording(
    rec: Any, segment: int, start_s: float, duration_s: float | None
) -> np.ndarray:
    """Extract a (n_samples, n_channels) numpy array from a Recording segment."""
    fs = float(rec.get_sampling_frequency())
    n_segments = rec.get_num_segments()
    if segment < 0 or segment >= n_segments:
        raise ValueError(f"segment {segment} out of range [0, {n_segments})")
    start_frame = round(start_s * fs)
    end_frame = None if duration_s is None else start_frame + round(duration_s * fs)
    # `return_in_uV` is the new name in spikeinterface 0.104+; older releases
    # accept `return_scaled=False`. Try the new API first, fall back gracefully.
    try:
        traces = rec.get_traces(
            segment_index=segment,
            start_frame=start_frame,
            end_frame=end_frame,
            return_in_uV=False,
        )
    except TypeError:
        traces = rec.get_traces(
            segment_index=segment,
            start_frame=start_frame,
            end_frame=end_frame,
            return_scaled=False,
        )
    if traces.ndim != 2:
        raise ValueError(f"Expected 2D traces, got shape {traces.shape}")
    return np.ascontiguousarray(traces)


@register("spikeinterface")
@register("si")
def load_spikeinterface(
    path: str | Path,
    reader: str = "auto",
    segment: int | str = 0,
    start_s: float | str = 0.0,
    duration_s: float | str | None = None,
    **reader_kwargs: Any,
) -> LoadedDataset:
    """Read a segment from any SpikeInterface-recognised recording.

    Args:
        path: file (`.nwb`, `.bin`, `.zarr`) or dir (`openephys`, `spikeglx`).
        reader: `"auto"` for detection, else any name of a
            `spikeinterface.extractors.read_<reader>` function.
        segment: index of the segment to read (usually 0).
        start_s, duration_s: slice of the segment in seconds.
        **reader_kwargs: forwarded to `read_<reader>()`.
    """
    if not _HAVE_SI:
        raise ImportError(
            "spikeinterface is not installed; `pip install spikeinterface` or install "
            "the `compbench[ephys]` extra."
        )
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"SpikeInterface path not found: {p}")

    if reader == "auto":
        reader = _detect_reader(p)
    reader_fn_name = f"read_{reader}"
    if not hasattr(_se, reader_fn_name):
        raise ValueError(
            f"spikeinterface.extractors has no `{reader_fn_name}`. "
            f"Check spikeinterface docs for the correct name."
        )
    reader_fn = getattr(_se, reader_fn_name)

    # Coerce string params from URI-scheme parsing.
    segment_i = int(segment)
    start = float(start_s)
    dur = None if duration_s in (None, "None", "") else float(duration_s)

    rec = reader_fn(p, **reader_kwargs)
    data = _slice_recording(rec, segment_i, start, dur)

    return LoadedDataset(
        data=data,
        sample_rate_hz=float(rec.get_sampling_frequency()),
        provenance={
            "loader": "spikeinterface",
            "params": {
                "path": str(p),
                "reader": reader,
                "segment": segment_i,
                "start_s": start,
                "duration_s": dur,
                "reader_kwargs": {k: str(v) for k, v in reader_kwargs.items()},
            },
            "spikeinterface": {
                "n_channels": int(rec.get_num_channels()),
                "n_segments": int(rec.get_num_segments()),
                "sampling_frequency_hz": float(rec.get_sampling_frequency()),
                "dtype": str(rec.get_dtype()),
            },
        },
    )
