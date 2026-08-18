"""LoadedDataset invariant: `data` is always C-contiguous.

Regression test: numcodecs codecs operate on flat memory in memory-layout
order. If a loader hands us an F-contiguous view (e.g. from `.T`), encode
would succeed but decode would produce garbled output.
"""

from __future__ import annotations

import numpy as np
import pytest

from compbench.datasets import load
from compbench.datasets.base import LoadedDataset


@pytest.mark.ai_generated
def test_c_contiguous_when_passed_f_order() -> None:
    a = np.arange(12, dtype=np.int16).reshape(3, 4).T  # F-contiguous view
    assert a.flags["F_CONTIGUOUS"] and not a.flags["C_CONTIGUOUS"]
    ds = LoadedDataset(data=a, sample_rate_hz=1.0)
    assert ds.data.flags["C_CONTIGUOUS"]
    assert np.array_equal(ds.data, a)


@pytest.mark.ai_generated
def test_synthetic_is_c_contiguous() -> None:
    ds = load("synthetic:duration_s=0.05,n_channels=3")
    assert ds.data.flags["C_CONTIGUOUS"]


@pytest.mark.ai_generated
def test_c_contiguous_untouched_when_already_c_order() -> None:
    a = np.arange(12, dtype=np.int16).reshape(3, 4)  # C-contiguous
    assert a.flags["C_CONTIGUOUS"]
    ds = LoadedDataset(data=a, sample_rate_hz=1.0)
    # ascontiguousarray on an already-contig array is a no-op; identity preserved.
    assert ds.data is a
