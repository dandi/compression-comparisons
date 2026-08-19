"""Parse T.261 encoder progress logs to estimate ETA.

Non-invasive: reads the on-disk stdout log written by `T261Codec._run_bwc`
(no coupling to the running process). The BWC encoder emits one
``... + <NUT-TYPE> bytes encoded: N`` line per encoded segment; counting
these plus the elapsed wall-time gives a rate that extrapolates to an
ETA if we know the total expected count. When the total isn't known
(most cases — the codec doesn't advertise its planned segment count
before running) we report just the rate + segments-so-far and let the
user compare against a completed reference run.

Deliberately does NOT change or observe the codec process itself —
safe to run against an active encode; safe to fail if the log is missing
or malformed; safe to invoke without any of compbench's runtime deps.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

_PROGRESS_RE = re.compile(rb"\+ \S+ bytes encoded:\s*(\d+)")


@dataclass
class T261Progress:
    """Snapshot of one T.261 encoder log."""

    log_path: Path
    segments_encoded: int
    log_size_bytes: int
    log_mtime_epoch: float
    wall_elapsed_s: float | None = None
    rate_seg_per_s: float | None = None
    eta_seconds: float | None = None
    expected_total_segments: int | None = None

    def human_line(self) -> str:
        parts = [f"{self.segments_encoded} segments encoded"]
        if self.wall_elapsed_s is not None:
            parts.append(f"in {self.wall_elapsed_s:.0f}s wall")
        if self.rate_seg_per_s and self.rate_seg_per_s > 0:
            parts.append(f"({self.rate_seg_per_s:.1f} seg/s)")
        if self.eta_seconds is not None:
            parts.append(f"ETA {self.eta_seconds:.0f}s")
        elif self.expected_total_segments is None and self.segments_encoded > 0:
            parts.append("(no expected total — pass --expected-segments to derive ETA)")
        return " ".join(parts)


def parse_log(
    log_path: str | Path,
    start_epoch: float | None = None,
    expected_total_segments: int | None = None,
) -> T261Progress:
    """Read an encoder stdout log and summarise progress.

    ``start_epoch`` — process start time (seconds since epoch); if given
    and the log has been mutated since, `rate_seg_per_s` and `eta_seconds`
    are computed.

    ``expected_total_segments`` — if known (e.g. from a prior completed
    run on similar data), ETA is `(expected - encoded) / rate`.

    Missing log → returns a zero-progress snapshot rather than raising.
    """
    p = Path(log_path)
    if not p.exists():
        return T261Progress(log_path=p, segments_encoded=0, log_size_bytes=0, log_mtime_epoch=0.0)
    st = p.stat()
    with p.open("rb") as f:
        blob = f.read()
    segments = len(_PROGRESS_RE.findall(blob))
    wall = None
    rate = None
    eta = None
    if start_epoch is not None:
        wall = max(0.0, st.st_mtime - start_epoch)
        if wall > 0 and segments > 0:
            rate = segments / wall
            if expected_total_segments and expected_total_segments > segments and rate > 0:
                eta = (expected_total_segments - segments) / rate
    return T261Progress(
        log_path=p,
        segments_encoded=segments,
        log_size_bytes=st.st_size,
        log_mtime_epoch=st.st_mtime,
        wall_elapsed_s=wall,
        rate_seg_per_s=rate,
        eta_seconds=eta,
        expected_total_segments=expected_total_segments,
    )


def find_active_encode_scratch(scratch_root: str | Path) -> Path | None:
    """Return the newest `enc-*/encode.stdout.log` under scratch_root, or None."""
    root = Path(scratch_root)
    if not root.is_dir():
        return None
    candidates = sorted(
        root.glob("enc-*/encode.stdout.log"),
        key=lambda p: p.stat().st_mtime if p.exists() else 0.0,
        reverse=True,
    )
    return candidates[0] if candidates else None


def watch(
    log_path: str | Path,
    interval_s: float = 5.0,
    expected_total_segments: int | None = None,
) -> None:
    """Poll a log every `interval_s` and print a one-line progress update.

    Exits when the log stops growing for 3 consecutive intervals — a
    reasonable heuristic for "process exited". Ctrl-C to stop early.
    """
    p = Path(log_path)
    start = p.stat().st_mtime if p.exists() else time.time()
    last_size = 0
    stalled = 0
    while True:
        snap = parse_log(p, start_epoch=start, expected_total_segments=expected_total_segments)
        print(f"[{time.strftime('%H:%M:%S')}] {snap.human_line()}")
        if snap.log_size_bytes == last_size:
            stalled += 1
            if stalled >= 3:
                print("(log stopped growing — process likely exited)")
                return
        else:
            stalled = 0
        last_size = snap.log_size_bytes
        time.sleep(interval_s)
