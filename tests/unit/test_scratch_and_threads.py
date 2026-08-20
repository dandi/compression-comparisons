"""Scratch volume and codec threading — operational guarantees.

Two ways a sweep can go wrong that no metric would reveal: filling the
host's root filesystem through TMPDIR, and letting the codec spawn threads
Snakemake doesn't know about, which makes every timing number a function of
how many neighbouring cells happened to be running.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import numcodecs.blosc as _blosc
import numpy as np
import pytest

from compbench.codecs import get as get_codec

REPO = Path(__file__).resolve().parents[2]


# ---- .env / .gitignore -------------------------------------------------


def _env_values() -> dict[str, str]:
    out = {}
    for line in (REPO / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def test_env_file_is_committed_and_defines_the_scratch_dir():
    assert (REPO / ".env").is_file(), ".env is committed on purpose — see DEPLOY §0"
    env = _env_values()
    assert env["COMPBENCH_TMPDIR"], "COMPBENCH_TMPDIR must be set"
    assert env["COMPBENCH_BLOSC_THREADS"] == "1"


def test_scratch_dir_is_gitignored():
    """Committing gigabytes of codec scratch would be an unpleasant surprise."""
    tmpdir = _env_values()["COMPBENCH_TMPDIR"].rstrip("/")
    patterns = {
        line.strip().rstrip("/")
        for line in (REPO / ".gitignore").read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    assert tmpdir in patterns, f"{tmpdir!r} must be in .gitignore; found {sorted(patterns)}"


def test_makefile_resolves_tmpdir_absolutely():
    """A relative TMPDIR silently follows the CWD; sweeps run from elsewhere."""
    mk = (REPO / "Makefile").read_text()
    assert "export TMPDIR" in mk
    assert "abspath" in mk
    assert re.search(r"^scratchdir:", mk, re.M)


def test_snakefile_resolves_tmpdir_independently_of_make():
    """The guarantee must hold when snakemake is invoked directly."""
    sf = (REPO / "src/compbench/pipeline/Snakefile").read_text()
    assert "_resolve_tmpdir" in sf
    assert 'os.environ["TMPDIR"] = TMPDIR' in sf
    assert "export TMPDIR=" in sf


# ---- blosc threading ---------------------------------------------------


def test_blosc_is_pinned_to_one_thread_by_default():
    assert _blosc.get_nthreads() == 1


def test_thread_count_is_recorded_in_the_codec_description():
    """CR does not depend on it, but byte-reproducibility does."""
    desc = get_codec("blosc-zstd")(level=9, shuffle="bit").describe()
    assert desc["blosc_nthreads"] == 1


@pytest.fixture
def signal():
    rng = np.random.default_rng(0)
    return np.cumsum(rng.normal(0, 30, size=(6000, 32)), axis=0).astype(np.int16)


def _encode(data, nthreads):
    prev = _blosc.get_nthreads()
    try:
        _blosc.set_nthreads(nthreads)
        return bytes(get_codec("blosc-zstd")(level=9, shuffle="bit").make_codec().encode(data))
    finally:
        _blosc.set_nthreads(prev)


def test_single_threaded_blosc_is_byte_reproducible(signal):
    """The reason for the pin: a benchmark claiming two runs agree should be
    able to produce the same bytes twice."""
    hashes = {hashlib.sha256(_encode(signal, 1)).hexdigest() for _ in range(3)}
    assert len(hashes) == 1


def test_compression_ratio_is_thread_count_independent(signal):
    """So the pin does not move any published number — only reproducibility.

    Multi-threaded blosc emits a different byte stream run to run, but the
    encoded LENGTH is stable, and CR is computed from the length.
    """
    lengths = {len(_encode(signal, n)) for n in (1, 2, 4)}
    assert len(lengths) == 1


def test_round_trip_is_exact_at_any_thread_count(signal):
    codec = get_codec("blosc-zstd")(level=9, shuffle="bit").make_codec()
    for n in (1, 4):
        out = np.frombuffer(codec.decode(_encode(signal, n)), dtype=signal.dtype)
        np.testing.assert_array_equal(out.reshape(signal.shape), signal)


def test_env_override_is_honoured(monkeypatch):
    """An operator can restore in-codec threading for a throughput run.

    Exercised through `_configure_threads` rather than a module reload —
    reloading re-runs the `@register` decorators and trips the duplicate
    registration guard.
    """
    from compbench.codecs.blosc import _configure_threads

    prev = _blosc.get_nthreads()
    try:
        monkeypatch.setenv("COMPBENCH_BLOSC_THREADS", "4")
        assert _configure_threads() == 4
        monkeypatch.setenv("COMPBENCH_BLOSC_THREADS", "1")
        assert _configure_threads() == 1
    finally:
        _blosc.set_nthreads(prev)


def test_tmpdir_default_is_not_the_root_filesystem():
    """Documented default must point somewhere with room, not /tmp."""
    assert not _env_values()["COMPBENCH_TMPDIR"].startswith("/tmp")
