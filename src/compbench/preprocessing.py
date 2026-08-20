"""Signal preprocessing applied to loaded datasets before encoding.

The paper (Buccino et al. 2023) applies a 300-6000 Hz band-pass filter before
compressing, which materially raises CR by attenuating the sub-300 Hz
low-frequency component that most codecs waste bits on. We expose this as a
first-class `preprocessing:` block on dataset YAMLs so both raw and
band-pass CR can sit alongside in the report.

Extend by adding a new function + registry entry — the codec + metric layers
don't care.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np

_DEFAULT_BLOCK_BYTES = 2 * 1024**3  # 2 GiB per float64 working array


def _bandpass(
    data: np.ndarray,
    sample_rate_hz: float,
    low_hz: float | str = 300.0,
    high_hz: float | str = 6000.0,
    order: int | str = 4,
    max_block_bytes: int | str = _DEFAULT_BLOCK_BYTES,
) -> np.ndarray:
    """Zero-phase band-pass filter (Butterworth via ``scipy.signal.filtfilt``).

    Filters per channel (axis=0). int16 input is filtered in float64 space
    and rounded/clipped back to int16 to preserve the original dtype —
    codec CRs must be comparable across preprocessed and raw variants.

    Filtering proceeds in **channel blocks** (plan §Phase 3.5 [R5-C1]).
    The whole-array form promoted a 27 GB int16 recording to 110 GB of
    float64 and handed that to ``filtfilt``, whose padding and internal
    copies pushed peak RSS to ~200-250 GB — enough to OOM anything under
    a 256 GB box, and enough to cap parallelism at ~4 cells even on 1 TB.
    Blocking by channel is exact: the filter runs along the time axis and
    is independent per channel, so a channel block produces bit-identical
    output to the whole-array call. Blocking by *time* would not — it
    would inject edge transients at every seam.

    Deliberately stays on the ``ba`` / ``filtfilt`` pair rather than moving
    to ``sosfiltfilt``. SOS is the numerically better representation at this
    order and is worth adopting, but it produces slightly different samples,
    which would silently shift every published band-pass CR and break
    comparability with the derivatives already in the study. That is a
    deliberate numerical change deserving its own evaluation, not a
    side-effect of a memory fix.
    """
    from scipy.signal import butter, filtfilt

    low = float(low_hz)
    high = float(high_hz)
    order_i = int(order)
    block_bytes = int(max_block_bytes)
    nyq = 0.5 * float(sample_rate_hz)
    if not 0 < low < high < nyq:
        raise ValueError(f"bandpass requires 0 < low ({low}) < high ({high}) < Nyquist ({nyq})")
    b, a = butter(order_i, [low / nyq, high / nyq], btype="band")

    original_dtype = data.dtype
    is_int = np.issubdtype(original_dtype, np.integer)
    info = np.iinfo(original_dtype) if is_int else None

    flat = data[:, None] if data.ndim == 1 else data
    n_samples, n_channels = flat.shape
    out = np.empty_like(flat)

    col_bytes = n_samples * 8
    cols_per_block = max(1, min(n_channels, block_bytes // max(col_bytes, 1)))

    peak = 0.0
    for c0 in range(0, n_channels, cols_per_block):
        c1 = min(c0 + cols_per_block, n_channels)
        filtered = filtfilt(b, a, flat[:, c0:c1].astype(np.float64), axis=0)
        if is_int:
            # Round in-place — `filtered` is a fresh array from filtfilt,
            # so mutating it is safe and saves a block-sized allocation.
            np.round(filtered, out=filtered)
            if filtered.size:
                peak = max(peak, float(np.max(np.abs(filtered))))
        out[:, c0:c1] = filtered.astype(original_dtype)
        del filtered

    if info is not None and peak > info.max:
        raise ValueError(
            f"bandpass: filter output would clip to {original_dtype} range "
            f"[{info.min}, {info.max}] — max abs = {peak:.1f}. Convert input "
            f"to a wider dtype (e.g. float32) or narrow the band."
        )
    return out.reshape(data.shape)


_REGISTRY: dict[str, Callable[..., np.ndarray]] = {
    "bandpass": _bandpass,
}


def apply(
    data: np.ndarray,
    sample_rate_hz: float,
    steps: list[dict[str, Any]] | None,
) -> np.ndarray:
    """Apply a sequence of preprocessing steps.

    ``steps`` is a list of dicts, each with a ``kind:`` key naming a
    registered preprocessor and additional keys passed as kwargs. Example
    from a dataset YAML::

        preprocessing:
          - kind: bandpass
            low_hz: 300
            high_hz: 6000
            order: 4
    """
    if not steps:
        return data
    out = data
    for i, step in enumerate(steps):
        kind = step.get("kind")
        if kind not in _REGISTRY:
            available = ", ".join(sorted(_REGISTRY)) or "<none>"
            raise ValueError(f"preprocessing[{i}]: unknown kind {kind!r}. Registered: {available}")
        kwargs = {k: v for k, v in step.items() if k != "kind"}
        out = _REGISTRY[kind](out, sample_rate_hz=sample_rate_hz, **kwargs)
    return out


def registered() -> list[str]:
    return sorted(_REGISTRY)
