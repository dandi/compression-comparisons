"""Loader for the AIND ephys-compression benchmark dataset
(`s3://aind-benchmark-data/ephys-compression/`, DataLad mirror at
`///aind-benchmark-data/ephys-compression`).

Each recording is stored as a SpikeInterface "binary folder": a directory
containing:
    binary.json      — BinaryRecordingExtractor kwargs (fs, num_chan, dtype, ...)
    probe.json       — probe geometry
    provenance.json  — history
    si_folder.json   — the object-graph SpikeInterface saved
    traces_cached_seg0.raw  — the raw int16 samples (annexed, ~25-55 GB)

The paper was written against SpikeInterface 0.94.1, and `si.core.load(path)`
in modern SI (0.104+) breaks on the metadata's channel_ids format. We
sidestep that by reading `binary.json` directly and constructing a
`BinaryRecordingExtractor` with the raw kwargs.

Registered as the `aind-benchmark:` scheme.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from compbench.datasets import register
from compbench.datasets.base import LoadedDataset

with contextlib.suppress(ImportError):
    from spikeinterface.core import BinaryRecordingExtractor as _BRE

_HAVE_SI = "_BRE" in globals()


def _load_recording(folder: Path) -> Any:
    """Construct a BinaryRecordingExtractor from a `binary_folder`-format dir."""
    if not _HAVE_SI:
        raise ImportError("spikeinterface is not installed; `pip install -e '.[ephys]'`.")
    binary_json = folder / "binary.json"
    if not binary_json.is_file():
        raise FileNotFoundError(f"expected {binary_json} — is {folder} an AIND ephys folder?")
    kw = json.loads(binary_json.read_text())["kwargs"]
    file_paths = [str(folder / p) for p in kw["file_paths"]]
    # Newer SI uses `num_channels`, older payloads say `num_chan` — pass both keys.
    n_chan = kw.get("num_channels", kw.get("num_chan"))
    return _BRE(
        file_paths=file_paths,
        sampling_frequency=kw["sampling_frequency"],
        num_channels=n_chan,
        dtype=kw["dtype"],
    )


@register("aind-benchmark")
def load_aind_benchmark(
    path: str | Path,
    start_s: float | str = 0.0,
    duration_s: float | str | None = None,
    channel_indices: str | list[int] | None = None,
) -> LoadedDataset:
    """Read a segment from one recording of the AIND ephys-compression dataset.

    Args:
        path: path to one recording folder, e.g.
            `.../ephys-compression/ibl-np1/CSHZAD026_2020-09-04_probe00`.
        start_s: start time within the recording (default 0).
        duration_s: length to slice (default: full recording).
        channel_indices: subset of channels (default: all).
    """
    folder = Path(path)
    if not folder.is_dir():
        raise FileNotFoundError(f"AIND ephys folder not found: {folder}")

    rec = _load_recording(folder)
    fs = float(rec.get_sampling_frequency())
    start = float(start_s)
    dur = None if duration_s in (None, "None", "") else float(duration_s)

    start_frame = round(start * fs)
    end_frame = None if dur is None else start_frame + round(dur * fs)
    traces = rec.get_traces(segment_index=0, start_frame=start_frame, end_frame=end_frame)
    if channel_indices is not None:
        idx = (
            channel_indices
            if isinstance(channel_indices, list)
            else [int(i) for i in str(channel_indices).split(",")]
        )
        traces = traces[:, idx]

    data = np.ascontiguousarray(traces)
    return LoadedDataset(
        data=data,
        sample_rate_hz=fs,
        provenance={
            "loader": "aind-benchmark",
            "params": {
                "path": str(folder),
                "start_s": start,
                "duration_s": dur,
                "channel_indices": (
                    None
                    if channel_indices is None
                    else list(map(int, str(channel_indices).split(",")))
                ),
            },
            "spikeinterface": {
                "n_channels_total": int(rec.get_num_channels()),
                "sampling_frequency_hz": fs,
                "dtype_native": str(rec.get_dtype()),
                "folder_name": folder.name,
            },
        },
    )
