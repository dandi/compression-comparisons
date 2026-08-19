"""Unit tests for compbench.t261_progress + `compbench t261-progress` CLI."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from click.testing import CliRunner

from compbench.cli import main
from compbench.t261_progress import (
    T261Progress,
    find_active_encode_scratch,
    parse_log,
)


def _make_log(path: Path, segments: int) -> None:
    lines = [f"... + FEATURE bytes encoded: {i * 4}" for i in range(1, segments + 1)]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


@pytest.mark.ai_generated
def test_parse_log_missing(tmp_path: Path) -> None:
    snap = parse_log(tmp_path / "no-such.log")
    assert snap.segments_encoded == 0
    assert snap.log_size_bytes == 0
    assert snap.rate_seg_per_s is None


@pytest.mark.ai_generated
def test_parse_log_counts_segments(tmp_path: Path) -> None:
    p = tmp_path / "encode.stdout.log"
    _make_log(p, 42)
    snap = parse_log(p)
    assert snap.segments_encoded == 42


@pytest.mark.ai_generated
def test_parse_log_ignores_non_progress_lines(tmp_path: Path) -> None:
    p = tmp_path / "encode.stdout.log"
    p.write_text(
        "Biomedical Waveform Codec (BWC), encoder ver. 6.0\n"
        "... + FEATURE bytes encoded: 100\n"
        "... + FEATURE bytes encoded: 200\n"
        "====== HLS info ends ======\n"
        "... + GLOBAL_CRC32_SPT bytes encoded: 1756\n"
    )
    snap = parse_log(p)
    # Progress-marker regex matches both FEATURE and GLOBAL_CRC32_SPT ("+ WORD bytes encoded: N")
    assert snap.segments_encoded == 3


@pytest.mark.ai_generated
def test_parse_log_rate_and_eta(tmp_path: Path) -> None:
    p = tmp_path / "encode.stdout.log"
    _make_log(p, 100)
    # Backdate mtime to 20s before "now"
    os.utime(p, (time.time() - 20, time.time()))
    snap = parse_log(p, start_epoch=time.time() - 30, expected_total_segments=200)
    # Rate = 100 segments / ~10 s wall elapsed (mtime is 20s ago; start_epoch was 30s ago)
    assert snap.rate_seg_per_s is not None and snap.rate_seg_per_s > 0
    assert snap.eta_seconds is not None
    # ETA should extrapolate the remaining 100 segments; must be > 0 and finite.
    assert snap.eta_seconds > 0


@pytest.mark.ai_generated
def test_parse_log_no_expected_no_eta(tmp_path: Path) -> None:
    p = tmp_path / "encode.stdout.log"
    _make_log(p, 100)
    snap = parse_log(p, start_epoch=time.time() - 10)
    # rate might be set; eta remains None without expected_total_segments
    assert snap.eta_seconds is None


@pytest.mark.ai_generated
def test_human_line_readable() -> None:
    snap = T261Progress(
        log_path=Path("x"),
        segments_encoded=100,
        log_size_bytes=1000,
        log_mtime_epoch=0.0,
        wall_elapsed_s=50.0,
        rate_seg_per_s=2.0,
        eta_seconds=25.0,
        expected_total_segments=150,
    )
    line = snap.human_line()
    assert "100 segments" in line
    assert "50s" in line
    assert "2.0" in line
    assert "25" in line  # ETA


@pytest.mark.ai_generated
def test_find_active_encode_scratch(tmp_path: Path) -> None:
    (tmp_path / "enc-1-abc").mkdir()
    (tmp_path / "enc-2-def").mkdir()
    old = tmp_path / "enc-1-abc" / "encode.stdout.log"
    new = tmp_path / "enc-2-def" / "encode.stdout.log"
    _make_log(old, 10)
    _make_log(new, 20)
    # Bump the new one's mtime forward.
    os.utime(new, (time.time(), time.time() + 5))
    found = find_active_encode_scratch(tmp_path)
    assert found == new


@pytest.mark.ai_generated
def test_find_active_encode_scratch_none(tmp_path: Path) -> None:
    assert find_active_encode_scratch(tmp_path) is None
    assert find_active_encode_scratch(tmp_path / "nowhere") is None


@pytest.mark.ai_generated
def test_cli_t261_progress_by_log(tmp_path: Path) -> None:
    p = tmp_path / "encode.stdout.log"
    _make_log(p, 25)
    r = CliRunner().invoke(main, ["t261-progress", "--log", str(p)])
    assert r.exit_code == 0, r.output
    assert "25 segments encoded" in r.output


@pytest.mark.ai_generated
def test_cli_t261_progress_by_scratch(tmp_path: Path) -> None:
    scratch = tmp_path / "scratch"
    (scratch / "enc-1-x").mkdir(parents=True)
    _make_log(scratch / "enc-1-x" / "encode.stdout.log", 7)
    r = CliRunner().invoke(main, ["t261-progress", "--scratch", str(scratch)])
    assert r.exit_code == 0, r.output
    assert "7 segments encoded" in r.output


@pytest.mark.ai_generated
def test_cli_t261_progress_requires_arg() -> None:
    r = CliRunner().invoke(main, ["t261-progress"])
    assert r.exit_code != 0
    assert "pass --log" in r.output


@pytest.mark.ai_generated
def test_cli_t261_progress_scratch_no_log(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    r = CliRunner().invoke(main, ["t261-progress", "--scratch", str(tmp_path / "empty")])
    assert r.exit_code != 0
    assert "no enc-*" in r.output


@pytest.mark.ai_generated
def test_progress_dir_preserves_scratch(tmp_path: Path) -> None:
    """End-to-end: T261Codec(progress_dir=...) keeps the encoder log on disk."""
    from compbench.codecs.t261 import _AVAILABLE, T261Codec

    if not _AVAILABLE:
        pytest.skip("BWC binaries not found")
    import numpy as np

    codec = T261Codec(progress_dir=tmp_path)
    data = np.arange(400, dtype=np.int16).reshape(100, 4)
    _ = codec.encode(data)
    logs = list(tmp_path.glob("enc-*/encode.stdout.log"))
    assert len(logs) >= 1
    snap = parse_log(logs[0])
    assert snap.segments_encoded > 0
