"""Common data class for loaded datasets."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class LoadedDataset:
    """A benchmark input.

    `data` is arranged (n_samples, n_channels) — the layout used throughout
    the neurophysiology tooling (SpikeInterface, WavPack). Codecs that need
    a different layout transpose internally.

    Invariant: `data` is C-contiguous. `numcodecs` codecs operate on flat
    memory in memory-layout order, so an F-contiguous array would encode
    correctly but decode into a garbled C-order buffer. We enforce
    contiguity at construction time so loaders can be careless.
    """

    data: np.ndarray
    sample_rate_hz: float
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.data.flags["C_CONTIGUOUS"]:
            self.data = np.ascontiguousarray(self.data)

    @property
    def n_samples(self) -> int:
        return int(self.data.shape[0])

    @property
    def n_channels(self) -> int:
        return int(self.data.shape[1]) if self.data.ndim > 1 else 1

    @property
    def duration_s(self) -> float:
        return self.n_samples / self.sample_rate_hz if self.sample_rate_hz > 0 else 0.0

    @property
    def nbytes(self) -> int:
        return int(self.data.nbytes)
