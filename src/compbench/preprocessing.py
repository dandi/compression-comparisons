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
    order: int | str = 5,
    variant: str = "spikeinterface",
    chunk_duration_s: float | str = 1.0,
    margin_ms: float | str = "auto",
    max_block_bytes: int | str = _DEFAULT_BLOCK_BYTES,
) -> np.ndarray:
    """Band-pass filter. Dispatches on `variant`.

    ``spikeinterface`` (default) delegates to
    ``spikeinterface.preprocessing.bandpass_filter`` and materialises it in
    the same chunks the paper's pipeline used. This is the reproduction
    path — see plan §6 decision 7. Matching by *calling* SpikeInterface
    rather than by reimplementing it removes a whole class of silent
    divergence: order, filter form, margin handling, edge behaviour and
    the round-then-cast are whatever SI does, by construction.

    ``legacy-o4-ba`` is the pre-2026-08-20 implementation (order 4,
    transposed-direct-form ``ba``, ``filtfilt`` over the whole buffer). It
    is retained ONLY so the three committed derivatives stay interpretable;
    it is not paper-comparable and must not be used for new reproduction
    cells.
    """
    # Validate before delegating: SpikeInterface raises its own message for
    # a bad band, which is correct but does not name the caller's parameters.
    # Keeping our check means the error still says which YAML field is wrong.
    low, high = float(low_hz), float(high_hz)
    nyq = 0.5 * float(sample_rate_hz)
    if not 0 < low < high < nyq:
        raise ValueError(f"bandpass requires 0 < low ({low}) < high ({high}) < Nyquist ({nyq})")

    _assert_no_int_overflow(data)

    if variant == "legacy-o4-ba":
        return _bandpass_legacy(
            data, sample_rate_hz, low_hz, high_hz, order=4, max_block_bytes=max_block_bytes
        )
    if variant != "spikeinterface":
        raise ValueError(
            f"bandpass variant must be 'spikeinterface' or 'legacy-o4-ba'; got {variant!r}"
        )
    return _bandpass_spikeinterface(
        data,
        sample_rate_hz,
        low_hz=float(low_hz),
        high_hz=float(high_hz),
        filter_order=int(order),
        chunk_duration_s=float(chunk_duration_s),
        margin_ms=margin_ms,
    )


def _bandpass_spikeinterface(
    data: np.ndarray,
    sample_rate_hz: float,
    low_hz: float,
    high_hz: float,
    filter_order: int,
    chunk_duration_s: float,
    margin_ms: float | str,
) -> np.ndarray:
    """Delegate to SpikeInterface, materialised in the paper's chunks.

    The paper calls ``spre.bandpass_filter(rec)`` — lazy — and the filter
    is actually applied per chunk when the recording is saved, with
    ``chunk_duration="1s"``. Each chunk is filtered with a margin either
    side that is then trimmed, so a whole-buffer filter is NOT the same
    operation: it differs at every chunk seam.

    Materialising chunk-by-chunk also bounds memory without any blocking
    logic of our own.
    """
    import spikeinterface.core as sc
    import spikeinterface.preprocessing as spre

    flat = data[:, None] if data.ndim == 1 else data
    rec = sc.NumpyRecording([flat], sampling_frequency=float(sample_rate_hz))
    filt = spre.bandpass_filter(
        rec,
        freq_min=low_hz,
        freq_max=high_hz,
        margin_ms=margin_ms,
        filter_order=filter_order,
        dtype=flat.dtype,
    )
    n = flat.shape[0]
    step = max(1, round(chunk_duration_s * float(sample_rate_hz)))
    out = np.empty_like(flat)
    for start in range(0, n, step):
        stop = min(start + step, n)
        out[start:stop] = filt.get_traces(start_frame=start, end_frame=stop)

    return out.reshape(data.shape)


def _assert_no_int_overflow(data: np.ndarray) -> None:
    """Refuse input a zero-phase band-pass could push outside its own dtype.

    SpikeInterface rounds and casts, which **wraps** on overflow: a filtered
    value of 33000 comes back as -32536, sign-flipped and silent. We match
    its arithmetic (plan §6 decision 7) rather than clamping, so the check
    has to happen on the way in.

    It cannot be done on the way out. Wrapping does not leave the result at
    an extreme — the wrapped value is an ordinary-looking number — so a
    post-hoc scan for saturated samples detects nothing.

    The trigger is input already at full scale: a zero-phase Butterworth
    rings past a step by several percent, so a sample at the dtype limit
    will overflow. Real extracellular data sits around +/-1000 counts of a
    +/-32767 range, so this never fires on a genuine recording.
    """
    if not np.issubdtype(data.dtype, np.integer):
        return
    info = np.iinfo(data.dtype)
    n_extreme = int(np.count_nonzero((data == info.min) | (data == info.max)))
    if n_extreme:
        raise ValueError(
            f"bandpass: input has {n_extreme} sample(s) at the {data.dtype} limit "
            f"[{info.min}, {info.max}], and a zero-phase filter rings beyond a step "
            f"— the output would clip. SpikeInterface wraps rather than saturating, "
            f"so this would silently return sign-flipped samples. Convert the input "
            f"to a wider dtype (e.g. float32) or narrow the band."
        )


def _bandpass_legacy(
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


def _lsb_correction(
    data: np.ndarray,
    sample_rate_hz: float,  # unused; preprocessors share one signature
    lsb: int | str,
    max_block_bytes: int | str = _DEFAULT_BLOCK_BYTES,
) -> np.ndarray:
    """Rescale acquisition-software-inflated samples back to an LSB of 1.

    Open Ephys rescales Neuropixels data to a fixed 0.195 uV/sample
    regardless of the hardware gain setting. For raw Neuropixels data that
    makes every stored sample an exact multiple of 12 (NP1) or 3 (NP2) —
    so log2(lsb) bits per sample carry no information, and general-purpose
    codecs that cannot see that structure waste them. SpikeGLX writes raw
    ADC values and already has an LSB of 1.

    Buccino et al. 2023 §2.2.1, verbatim:

        Prior to compression, we rescaled the Open Ephys data to have an
        LSB of 1 by first removing each channel's median (since scaling
        could introduce rounding errors) and dividing by either 12 or 3.

    Median removal comes first for exactly the stated reason: the DC
    offset is not itself a multiple of `lsb`, so dividing without
    centring would leave a fractional remainder that rounds
    inconsistently across channels.

    ``lsb=1`` is a NO-OP, matching ``spikeinterface.preprocessing.correct_lsb``
    ("Estimated LSB=1. No operation is applied"). This is not a detail:
    the paper's own driver marks IBL as ``{"none": False}`` — *"spikeGLX
    is already LSB-corrected"* — and passes the untouched recording to the
    compressor. Removing the median anyway is a preprocessing step the
    paper never applied, and on CSHZAD026 it inflates blosc-zstd CR by
    over 20%, i.e. enough to fake a failed reproduction.

    Pass the recording's own LSB from the paper's table 1 (IBL NP1: 1,
    AIND NP1: 12, AIND NP2: 3); an IBL recording therefore needs no
    ``lsb`` condition at all.

    This is an added condition, never a correction applied in place —
    see plan §6 decision 6. Uncorrected AIND numbers stand on their own.
    """
    lsb_i = int(lsb)
    if lsb_i < 1:
        raise ValueError(f"lsb must be a positive integer; got {lsb_i}")
    if lsb_i == 1:
        # Matches spikeinterface.preprocessing.correct_lsb. See docstring.
        return data

    flat = data[:, None] if data.ndim == 1 else data
    n_samples, n_channels = flat.shape
    original_dtype = data.dtype
    if n_samples == 0 or n_channels == 0:
        return data

    # Per-channel median over the full time axis, so block by channel.
    block_bytes = int(max_block_bytes)
    col_bytes = n_samples * 8
    cols_per_block = max(1, min(n_channels, block_bytes // max(col_bytes, 1)))

    out = np.empty_like(flat)
    is_int = np.issubdtype(original_dtype, np.integer)
    for c0 in range(0, n_channels, cols_per_block):
        c1 = min(c0 + cols_per_block, n_channels)
        block = flat[:, c0:c1].astype(np.float64)
        block -= np.median(block, axis=0, keepdims=True)
        block /= lsb_i
        if is_int:
            np.round(block, out=block)
        out[:, c0:c1] = block.astype(original_dtype)
        del block
    return out.reshape(data.shape)


_REGISTRY: dict[str, Callable[..., np.ndarray]] = {
    "bandpass": _bandpass,
    "lsb_correction": _lsb_correction,
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
