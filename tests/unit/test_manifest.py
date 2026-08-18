"""Unit tests for compbench.manifest."""

from __future__ import annotations

import numpy as np
import pytest

from compbench.manifest import array_digest, build_manifest, git_sha, input_digest


@pytest.mark.ai_generated
def test_input_digest_deterministic() -> None:
    a = input_digest(b"hello")
    b = input_digest(b"hello")
    c = input_digest(b"HELLO")
    assert a == b
    assert a != c
    assert len(a) == 64  # sha256 hex


@pytest.mark.ai_generated
def test_array_digest_distinguishes_reshapes() -> None:
    # Two arrays with identical bytes but different shape MUST hash differently
    # so the manifest join key doesn't collide.
    base = np.arange(400, dtype=np.int16)
    a = base.reshape(100, 4)
    b = base.reshape(200, 2)
    assert array_digest(a) != array_digest(b)


@pytest.mark.ai_generated
def test_array_digest_distinguishes_dtypes() -> None:
    a = np.arange(200, dtype=np.int16).reshape(100, 2)
    b = np.arange(100, dtype=np.int32).reshape(100, 1)  # same total bytes
    assert array_digest(a) != array_digest(b)


@pytest.mark.ai_generated
def test_array_digest_stable_across_layouts() -> None:
    # Same logical array, different memory layout (C vs F) → same digest.
    a = np.arange(24, dtype=np.int16).reshape(6, 4)
    b = np.ascontiguousarray(a.T.T)  # roundtrip through F, back to C
    assert array_digest(a) == array_digest(b)


@pytest.mark.ai_generated
def test_git_sha_returns_str_or_none() -> None:
    sha = git_sha()
    assert sha is None or (isinstance(sha, str) and len(sha) == 40)


@pytest.mark.ai_generated
def test_build_manifest_shape() -> None:
    arr = np.zeros((100, 4), dtype=np.int16)
    m = build_manifest(
        dataset_provenance={"loader": "synthetic"},
        codec_description={"name": "blosc-zstd", "lossy": False, "params": {"level": 3}},
        input_array=arr,
        sample_rate_hz=1000.0,
        duration_s=1.0,
    )
    assert m["input"]["nbytes"] == arr.nbytes
    assert m["input"]["sha256"] == array_digest(arr)
    assert m["input"]["n_channels"] == 4
    assert m["input"]["shape"] == [100, 4]
    assert m["input"]["dtype"] == "int16"
    assert m["codec"]["name"] == "blosc-zstd"
    assert "compbench_version" in m
    assert "created_utc" in m
    assert "python" in m and "platform" in m


@pytest.mark.ai_generated
def test_build_manifest_extra_passthrough() -> None:
    m = build_manifest(
        dataset_provenance={},
        codec_description={"name": "x", "lossy": False, "params": {}},
        input_array=np.zeros(1, dtype=np.int16),
        sample_rate_hz=1.0,
        duration_s=0.0,
        extra={"note": "hello"},
    )
    assert m["extra"] == {"note": "hello"}
