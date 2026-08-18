"""Round-trip smoke for every registered lossless codec.

Parametrised so adding a codec adds a test row automatically; catches
registration issues (typos in `name`, missing `make_codec`) and
lossless correctness at once.
"""

from __future__ import annotations

import numpy as np
import pytest

from compbench import codecs
from compbench.codecs.base import CodecAdapter

_STRUCTURED = np.tile(
    (1000 * np.sin(np.linspace(0, 6, 4000))).astype(np.int16).reshape(-1, 1),
    (1, 4),
)


def _lossless_adapters() -> list[type[CodecAdapter]]:
    return [cls for cls in codecs.all_adapters() if cls().lossy is False]


@pytest.mark.ai_generated
@pytest.mark.parametrize("cls", _lossless_adapters(), ids=lambda c: c.name)
def test_lossless_round_trip(cls: type[CodecAdapter]) -> None:
    adapter = cls()
    codec = adapter.make_codec()
    encoded = codec.encode(_STRUCTURED)
    decoded = np.frombuffer(codec.decode(encoded), dtype=_STRUCTURED.dtype).reshape(
        _STRUCTURED.shape
    )
    assert np.array_equal(_STRUCTURED, decoded), f"{cls.name} broke round-trip"


@pytest.mark.ai_generated
@pytest.mark.parametrize("cls", _lossless_adapters(), ids=lambda c: c.name)
def test_lossless_compresses_structured_data(cls: type[CodecAdapter]) -> None:
    adapter = cls()
    codec = adapter.make_codec()
    encoded = codec.encode(_STRUCTURED)
    assert len(encoded) < _STRUCTURED.nbytes, (
        f"{cls.name} did not compress a slowly-varying signal (structured)."
    )


@pytest.mark.ai_generated
def test_all_paper_lossless_codecs_registered() -> None:
    # The Buccino et al. 2023 paper's lossless codec set. WavPack + FLAC are
    # optional (separate packages), so we don't require them here.
    required = {
        "blosc-lz4",
        "blosc-lz4hc",
        "blosc-zlib",
        "blosc-zstd",
        "gzip",
        "zlib",
        "lz4",
        "zstd",
        "lzma",
    }
    missing = required - set(codecs.names())
    assert not missing, f"Missing required codecs: {missing}"


@pytest.mark.ai_generated
@pytest.mark.parametrize(
    "name,params",
    [
        ("blosc-zstd", {"level": 5, "shuffle": "bit"}),
        ("blosc-lz4", {"level": 3, "shuffle": "byte"}),
        ("blosc-lz4hc", {"level": 9}),
        ("blosc-zlib", {"level": 6, "shuffle": "none"}),
        ("gzip", {"level": 9}),
        ("zlib", {"level": 9}),
        ("lz4", {"acceleration": 3}),
        ("zstd", {"level": 10}),
        ("lzma", {"preset": 3}),
    ],
)
def test_params_forwarded_and_survive_describe(name: str, params: dict) -> None:
    adapter = codecs.get(name)(**params)
    desc = adapter.describe()
    for k, v in params.items():
        assert desc["params"][k] == v, f"{name}: param {k} not preserved in describe()"
