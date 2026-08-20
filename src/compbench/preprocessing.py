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


def _bandpass(
    data: np.ndarray,
    sample_rate_hz: float,
    low_hz: float | str = 300.0,
    high_hz: float | str = 6000.0,
    order: int | str = 4,
) -> np.ndarray:
    """Zero-phase band-pass filter (Butterworth via ``scipy.signal.filtfilt``).

    Filters per channel (axis=0). Uses ``scipy`` if available; otherwise
    raises ImportError with a clear message. int16 input is filtered in
    float64 space and rounded/clipped back to int16 to preserve the
    original dtype — codec CRs must be comparable across preprocessed
    and raw variants.
    """
    from scipy.signal import butter, filtfilt

    low = float(low_hz)
    high = float(high_hz)
    order_i = int(order)
    nyq = 0.5 * float(sample_rate_hz)
    if not 0 < low < high < nyq:
        raise ValueError(f"bandpass requires 0 < low ({low}) < high ({high}) < Nyquist ({nyq})")
    b, a = butter(order_i, [low / nyq, high / nyq], btype="band")

    original_dtype = data.dtype
    working = data.astype(np.float64, copy=False)
    # filtfilt on axis=0 (samples), independent per channel.
    filtered = filtfilt(b, a, working, axis=0)
    if np.issubdtype(original_dtype, np.integer):
        info = np.iinfo(original_dtype)
        # Round in-place to save one full-array allocation (round-2 R5-C1'):
        # on 27 GB int16 input this is a ~110 GB saving. `filtered` is a
        # fresh array from filtfilt so mutating it is safe.
        np.round(filtered, out=filtered)
        # Clip check — the abs-max scan avoids materialising an intermediate
        # boolean mask (~13 GB on 27 GB input). Cost: one O(N) pass.
        peak = float(np.max(np.abs(filtered))) if filtered.size else 0.0
        if peak > info.max:
            raise ValueError(
                f"bandpass: filter output would clip to {original_dtype} range "
                f"[{info.min}, {info.max}] — max abs = {peak:.1f}. Convert input "
                f"to a wider dtype (e.g. float32) or narrow the band."
            )
    return np.ascontiguousarray(filtered.astype(original_dtype))


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
