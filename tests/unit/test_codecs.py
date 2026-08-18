"""Unit tests for compbench.codecs."""

from __future__ import annotations

import numpy as np
import pytest

from compbench import codecs


@pytest.mark.ai_generated
def test_blosc_zstd_registered() -> None:
    assert "blosc-zstd" in codecs.names()


@pytest.mark.ai_generated
def test_blosc_zstd_defaults_lossless() -> None:
    adapter = codecs.get("blosc-zstd")()
    assert adapter.lossy is False
    desc = adapter.describe()
    assert desc["name"] == "blosc-zstd"
    assert desc["params"]["level"] == 3
    assert desc["params"]["shuffle"] == "byte"


@pytest.mark.ai_generated
def test_blosc_zstd_round_trip_int16() -> None:
    rng = np.random.default_rng(0)
    data = rng.integers(-10_000, 10_000, size=(2000, 8), dtype=np.int16)
    adapter = codecs.get("blosc-zstd")(level=5, shuffle="bit")
    codec = adapter.make_codec()
    encoded = codec.encode(data)
    decoded = np.frombuffer(codec.decode(encoded), dtype=np.int16).reshape(data.shape)
    assert np.array_equal(data, decoded)
    # random noise does not compress — do not assert CR > 1 here.


@pytest.mark.ai_generated
def test_blosc_zstd_compresses_structured_data() -> None:
    # A slowly-varying signal — should compress well.
    t = np.linspace(0, 1, 4000, dtype=np.float64)
    data = (1000 * np.sin(2 * np.pi * 3 * t)).astype(np.int16).reshape(-1, 1)
    adapter = codecs.get("blosc-zstd")(level=5, shuffle="byte")
    codec = adapter.make_codec()
    encoded = codec.encode(data)
    assert len(encoded) < data.nbytes  # structured data compresses


@pytest.mark.ai_generated
def test_blosc_zstd_bad_shuffle() -> None:
    with pytest.raises(ValueError):
        codecs.get("blosc-zstd")(shuffle="foobar")


@pytest.mark.ai_generated
def test_blosc_zstd_level_coerces_from_string() -> None:
    adapter = codecs.get("blosc-zstd")(level="7")
    desc = adapter.describe()
    assert desc["params"]["level"] == 7


@pytest.mark.ai_generated
def test_registry_unknown() -> None:
    with pytest.raises(KeyError):
        codecs.get("no-such-codec")


@pytest.mark.ai_generated
def test_registry_no_duplicate_names() -> None:
    from compbench.codecs import base, register

    class Fake(base.CodecAdapter):
        name = "blosc-zstd"

    with pytest.raises(ValueError):
        register(Fake)
