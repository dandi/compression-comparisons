"""Unit tests for compbench.manifest."""

from __future__ import annotations

import pytest

from compbench.manifest import build_manifest, git_sha, input_digest


@pytest.mark.ai_generated
def test_input_digest_deterministic() -> None:
    a = input_digest(b"hello")
    b = input_digest(b"hello")
    c = input_digest(b"HELLO")
    assert a == b
    assert a != c
    assert len(a) == 64  # sha256 hex


@pytest.mark.ai_generated
def test_git_sha_returns_str_or_none() -> None:
    sha = git_sha()
    assert sha is None or (isinstance(sha, str) and len(sha) == 40)


@pytest.mark.ai_generated
def test_build_manifest_shape() -> None:
    m = build_manifest(
        dataset_provenance={"loader": "synthetic"},
        codec_description={"name": "blosc-zstd", "lossy": False, "params": {"level": 3}},
        input_bytes=b"x" * 100,
        sample_rate_hz=1000.0,
        duration_s=1.0,
        n_channels=4,
        dtype="int16",
    )
    assert m["input"]["nbytes"] == 100
    assert m["input"]["sha256"] == input_digest(b"x" * 100)
    assert m["input"]["n_channels"] == 4
    assert m["codec"]["name"] == "blosc-zstd"
    assert "compbench_version" in m
    assert "created_utc" in m
    assert "python" in m and "platform" in m


@pytest.mark.ai_generated
def test_build_manifest_extra_passthrough() -> None:
    m = build_manifest(
        dataset_provenance={},
        codec_description={"name": "x", "lossy": False, "params": {}},
        input_bytes=b"",
        sample_rate_hz=1.0,
        duration_s=0.0,
        n_channels=1,
        dtype="int16",
        extra={"note": "hello"},
    )
    assert m["extra"] == {"note": "hello"}
