"""MEArec dataset loader — simulated ephys with ground-truth spike times.

The Buccino et al. 2023 paper uses MEArec-simulated recordings (NP1 & NP2,
600 s, 100 GT units, 10 µV additive spatially correlated noise) as the
ground-truth substrate for lossy-compression sorting-fidelity evaluation
(paper §3.2.2, Figs 10-11).

MEArec files are HDF5 (`.h5`) — SpikeInterface's `read_mearec()` returns
BOTH a `RecordingExtractor` (the waveform data we compress) and a
`SortingExtractor` (the ground-truth spike times / labels). This loader
returns only the compressible-recording view; the ground-truth sorting is
fetched separately by the sorting-eval pipeline via `load_ground_truth()`
so `compbench run` cells don't carry sorting objects (they don't need them).

Registers the `mearec:` scheme.

Only imported (and thus registered) if `spikeinterface` is installed. Actual
`read_mearec` also requires `MEArec` and `neo` to be installed — those come
in with `pip install -e '.[ephys]'`.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

import numpy as np

from compbench.datasets import register
from compbench.datasets.base import LoadedDataset

with contextlib.suppress(ImportError):
    from spikeinterface.extractors import read_mearec as _read_mearec

_HAVE_MEAREC = "_read_mearec" in globals()


@register("mearec")
def load_mearec(
    path: str | Path,
    start_s: float | str = 0.0,
    duration_s: float | str | None = None,
) -> LoadedDataset:
    """Load a MEArec `.h5` recording as (n_samples, n_channels) int16 array.

    Args:
        path: path to a MEArec `.h5` (e.g.
            `sourcedata/aind-ephys-compression/mearec/mearec_NP1.h5`).
        start_s / duration_s: window to slice from the recording.

    Ground-truth sorting is NOT returned here (kept out of the compression
    hot path). Fetch it via `compbench.datasets.mearec.load_ground_truth(path)`
    from the sorting-eval pipeline.
    """
    if not _HAVE_MEAREC:
        raise ImportError(
            "spikeinterface.extractors.read_mearec unavailable; "
            "install with `pip install -e '.[ephys]' MEArec neo`."
        )
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"MEArec file not found: {p}")

    rec, _ = _read_mearec(str(p))
    fs = float(rec.get_sampling_frequency())
    start = float(start_s)
    dur = None if duration_s in (None, "None", "") else float(duration_s)
    start_frame = round(start * fs)
    end_frame = None if dur is None else start_frame + round(dur * fs)
    traces = rec.get_traces(segment_index=0, start_frame=start_frame, end_frame=end_frame)

    return LoadedDataset(
        data=np.ascontiguousarray(traces),
        sample_rate_hz=fs,
        provenance={
            "loader": "mearec",
            "params": {"path": str(p), "start_s": start, "duration_s": dur},
            "mearec": {
                "n_channels": int(rec.get_num_channels()),
                "n_segments": int(rec.get_num_segments()),
                "dtype_native": str(rec.get_dtype()),
                "has_ground_truth_sorting": True,
            },
        },
    )


def load_ground_truth(path: str | Path) -> Any:
    """Return the ground-truth `SortingExtractor` for a MEArec file.

    Used by the sorting-eval pipeline stage (see plan §4.7). Not needed
    by `compbench run` cells.
    """
    if not _HAVE_MEAREC:
        raise ImportError("read_mearec unavailable; install ephys extras.")
    _, sorting = _read_mearec(str(path))
    return sorting
