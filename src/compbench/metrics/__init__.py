"""Correctness metrics: CR, RMSE, round-trip byte-equality."""

from __future__ import annotations

import numpy as np


def compression_ratio(original_bytes: int, encoded_bytes: int) -> float:
    """`original / encoded`. Undefined for empty input; returns 0.0."""
    if encoded_bytes <= 0:
        return 0.0
    return original_bytes / encoded_bytes


def rmse(original: np.ndarray, reconstructed: np.ndarray) -> float:
    """Root-mean-square error in the units of the input."""
    if original.shape != reconstructed.shape:
        raise ValueError(
            f"Shape mismatch: original {original.shape} vs reconstructed {reconstructed.shape}"
        )
    if original.dtype != reconstructed.dtype:
        # Coerce reconstructed to original dtype before diff to catch codec dtype bugs.
        reconstructed = reconstructed.astype(original.dtype)
    diff = original.astype(np.float64) - reconstructed.astype(np.float64)
    return float(np.sqrt(np.mean(diff * diff)))


def round_trip_ok(original: np.ndarray, reconstructed: np.ndarray) -> bool:
    """True iff shape, dtype, and every byte match exactly."""
    if original.shape != reconstructed.shape:
        return False
    if original.dtype != reconstructed.dtype:
        return False
    return bool(np.array_equal(original, reconstructed))


__all__ = ["compression_ratio", "rmse", "round_trip_ok"]
