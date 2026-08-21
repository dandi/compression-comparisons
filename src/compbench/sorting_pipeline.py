"""The three stages of the lossy-vs-sorting evaluation (plan §4.6c).

    compress    raw traces --LOSSY--> stored Zarr + distortion metrics
    spikesort   stored recording -> stored sorting
    compare     sorting + ground truth -> sorting-fidelity metrics

Three commands, not one, because their inputs vary independently and the
expensive middle stage must not be repeated for a change in the cheap outer
ones. Compression is the variable under study and costs hours per cell;
sorting is expensive and plural (Kilosort 4 now, possibly Kilosort 2.5 in a
container later); comparison is cheap and still moving. Each stage writes a
durable artifact the next consumes.

The stored artifact is a **Zarr store**, which is what the paper compresses
into — so the compression ratio is measured on the same object it measured
— and which, unlike a bare array, carries probe geometry, channel locations
and gains. The gains are load-bearing: after LSB correction anything
denominated in uV is otherwise wrong by 12x (NP1) or 3x (NP2).
"""

from __future__ import annotations

import contextlib
import json
import time
from pathlib import Path
from typing import Any

import numpy as np

from compbench import codecs
from compbench.manifest import git_sha


def _versions() -> dict[str, Any]:
    """Environment facts a number cannot be reproduced without."""
    import platform
    import sys

    import numcodecs
    import spikeinterface

    out: dict[str, Any] = {
        "python": sys.version.split()[0],
        "numcodecs": numcodecs.__version__,
        "spikeinterface": spikeinterface.__version__,
        "compbench_git_sha": git_sha(),
        "platform": platform.platform(),
        "libc": "-".join(platform.libc_ver()),
    }
    try:
        import torch

        out["torch"] = torch.__version__
        out["cuda_device"] = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
    except ImportError:
        pass
    return out


def compress(
    recording: Any,  # spikeinterface BaseRecording
    codec_name: str,
    codec_params: dict[str, Any],
    out_dir: Path,
    chunk_duration_s: float = 1.0,
    n_jobs: int = 1,
    rmse_window_s: tuple[float, float] = (15.0, 20.0),
) -> dict[str, Any]:
    """Stage 1 — compress to a Zarr store and measure signal-level distortion.

    Writes `<out_dir>/compressed.zarr` plus `compress-metrics.json`. The
    Zarr is the artifact stages 2 and 3 consume, and it is deliberately
    kept: recompressing to change a sorter is the waste this split exists
    to avoid.

    Distortion is measured on the band-passed difference over
    `rmse_window_s`, matching the paper's `benchmark_lossy_compression`
    (which uses a 5 s window at 15-20 s, despite the text saying 10 s).
    """
    import spikeinterface.preprocessing as spre
    from spikeinterface.core.zarrextractors import ZarrRecordingExtractor

    out_dir.mkdir(parents=True, exist_ok=True)
    adapter = codecs.get(codec_name)(**codec_params)
    zarr_path = out_dir / "compressed.zarr"
    if zarr_path.exists():
        import shutil

        shutil.rmtree(zarr_path)

    filters = adapter.make_filters()
    t0 = time.perf_counter()
    compressed = recording.save(
        format="zarr",
        folder=zarr_path,
        compressor=adapter.make_codec(),
        filters=filters or None,
        chunk_duration=f"{chunk_duration_s}s",
        n_jobs=n_jobs,
        progress_bar=False,
        verbose=False,
    )
    encode_s = time.perf_counter() - t0

    # Compression ratio, measured on the Zarr store — the same object the
    # paper measures (`nbytes / nbytes_stored`, i.e. logical size over
    # on-disk chunk bytes). `.save()` does NOT set the annotation; SI only
    # populates it when a store is *read back* with
    # `load_compression_ratio=True`, so re-read rather than trusting an
    # annotation that is silently None.
    # `read_zarr()` does not forward the flag; construct the extractor directly.
    compressed = ZarrRecordingExtractor(zarr_path, load_compression_ratio=True)
    cr_annot = compressed.get_annotation("compression_ratio")
    if cr_annot is None:  # pragma: no cover - defensive across SI versions
        raise RuntimeError(
            f"Zarr store at {zarr_path} reports no compression_ratio; "
            f"cannot measure CR for {codec_name}."
        )
    cr = float(cr_annot)

    # Band-pass both sides and difference over the paper's window.
    fs = recording.get_sampling_frequency()
    a, b = (int(x * fs) for x in rmse_window_s)
    n = recording.get_num_frames()
    a, b = min(a, n), min(b, n)
    ref = spre.bandpass_filter(recording, freq_min=300, freq_max=6000)
    lossy = spre.bandpass_filter(compressed, freq_min=300, freq_max=6000)
    d = ref.get_traces(start_frame=a, end_frame=b, return_scaled=True).astype(np.float64)
    e = lossy.get_traces(start_frame=a, end_frame=b, return_scaled=True).astype(np.float64)
    err = d - e
    rmse_uv = float(np.sqrt((err**2).mean()))

    # Byte-exactness on the raw traces, which is what "lossless" means here.
    raw_ref = recording.get_traces(start_frame=a, end_frame=b)
    raw_lossy = compressed.get_traces(start_frame=a, end_frame=b)
    exact = bool(np.array_equal(raw_ref, raw_lossy))

    metrics = {
        "codec": adapter.describe(),
        "cr": cr,
        "encode_s": encode_s,
        "encode_xrt": recording.get_total_duration() / encode_s if encode_s else None,
        "rmse_uv": rmse_uv,
        "rmse_window_s": list(rmse_window_s),
        "round_trip_exact": exact,
        "expected_lossless": not adapter.lossy,
        "lossless_violation": (not adapter.lossy) and not exact,
        "chunk_duration_s": chunk_duration_s,
        "duration_s": recording.get_total_duration(),
        "n_channels": recording.get_num_channels(),
        "sampling_frequency_hz": fs,
        "zarr_path": str(zarr_path),
        "versions": _versions(),
    }
    (out_dir / "compress-metrics.json").write_text(json.dumps(metrics, indent=2, default=str))
    return metrics


def spikesort(
    zarr_path: Path,
    out_dir: Path,
    sorter: str = "kilosort4",
    sorter_params: dict[str, Any] | None = None,
    bandpass: tuple[float, float] | None = (300.0, 6000.0),
    common_reference: bool = False,
    n_jobs: int = 1,
) -> dict[str, Any]:
    """Stage 2 — sort a stored recording.

    `common_reference` defaults False: the paper applies CMR to experimental
    data only, never to the simulated ground-truth path. Note this means "no
    external CMR" — the sorter's own internal CAR stays at its default,
    which is what the paper's Kilosort 2.5 run did.
    """
    import spikeinterface as si
    import spikeinterface.preprocessing as spre
    from spikeinterface.sorters import run_sorter

    out_dir.mkdir(parents=True, exist_ok=True)
    rec = si.read_zarr(zarr_path)
    if bandpass is not None:
        rec = spre.bandpass_filter(rec, freq_min=bandpass[0], freq_max=bandpass[1])
    if common_reference:
        rec = spre.common_reference(rec)

    t0 = time.perf_counter()
    sorting = run_sorter(
        sorter,
        rec,
        folder=out_dir / "sorter_output",
        remove_existing_folder=True,
        verbose=False,
        **(sorter_params or {}),
    )
    sort_s = time.perf_counter() - t0
    saved = sorting.save(folder=out_dir / "sorting")

    from spikeinterface.sorters import sorter_dict

    version = "unknown"
    # Version probing must never fail a run that already succeeded.
    with contextlib.suppress(Exception):
        version = sorter_dict[sorter].get_sorter_version()

    info = {
        "sorter": sorter,
        "sorter_version": str(version),
        "sorter_params": sorter_params or {},
        "presort": {
            "bandpass_hz": list(bandpass) if bandpass else None,
            "common_reference": common_reference,
        },
        "n_units": len(saved.unit_ids),
        "n_spikes": int(sum(len(saved.get_unit_spike_train(u)) for u in saved.unit_ids)),
        "sort_s": sort_s,
        "sorting_path": str(out_dir / "sorting"),
        "zarr_path": str(zarr_path),
        "versions": _versions(),
    }
    (out_dir / "sort-info.json").write_text(json.dumps(info, indent=2, default=str))
    return info


def compare_to_ground_truth(
    sorting_path: Path,
    ground_truth: Any,
    out_dir: Path,
    **comparison_kwargs: Any,
) -> dict[str, Any]:
    """Stage 3 — sorting fidelity against ground truth.

    Cheap and re-runnable: changing a threshold re-derives from the stored
    sorting without re-sorting, let alone recompressing.
    """
    import spikeinterface as si

    from compbench.metrics.sorting import gt_comparison_metrics

    out_dir.mkdir(parents=True, exist_ok=True)
    sorting = si.load(sorting_path)
    result = gt_comparison_metrics(ground_truth, sorting, **comparison_kwargs)
    result["versions"] = _versions()
    (out_dir / "sorting-metrics.json").write_text(json.dumps(result, indent=2, default=str))
    return result
