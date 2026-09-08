"""ITU-T T.261 / ISO/IEC 23003-8 (H.BWC) codec — subprocess-based adapter.

This is the Phase 2 *stopgap* implementation: each encode/decode shells out
to the `EncoderApp` / `DecoderApp` binaries produced by the BWC reference
software (`src/bwc/`). It is registered as `t261` in `compbench.codecs` so it
drops into the sweep with no orchestration changes.

The proper in-process pybind11 wrapper (`t261-numcodecs`, Phase 2b) will
replace this file with identical Python-side API and the same `codec_id`,
so profile YAMLs and results stay comparable.

Binary + config discovery order:
    1. ``BWC_BIN_DIR`` env var (dir containing ``EncoderApp`` / ``DecoderApp``)
    2. ``$PATH`` lookup for ``EncoderApp`` / ``DecoderApp``
    3. Repo-relative default: ``src/bwc/bin/release/``

The codec adapter is registered only if all three of those lookups produce
a working binary — otherwise the `t261` name simply isn't listed.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
from numcodecs.abc import Codec
from numcodecs.registry import register_codec

from compbench.codecs import register
from compbench.codecs.base import CodecAdapter

_ENCODER_NAME = "EncoderApp"
_DECODER_NAME = "DecoderApp"

# Header format documented by the BWC ref-sw reference (see subagent review):
#   uint16  n_channels    (LE)
#   uint16  bit_depth     (LE)
#   int16   sample[0][0], sample[0][1], ..., sample[N-1][C-1]  (LE, interleaved)
_RAWH2_HEADER = struct.Struct("<HH")


def _repo_bwc_bin() -> Path:
    """Best-effort discovery of the repo-local `src/bwc/bin/release/` dir."""
    here = Path(__file__).resolve()
    # …/src/compbench/codecs/t261.py → parents[3] == repo root
    for parent in here.parents:
        candidate = parent / "src" / "bwc" / "bin" / "release"
        if candidate.is_dir():
            return candidate
    return Path()  # empty — signals "not found"


def _resolve_binary(name: str) -> Path | None:
    env_dir = os.environ.get("BWC_BIN_DIR")
    if env_dir:
        p = Path(env_dir) / name
        if p.is_file() and os.access(p, os.X_OK):
            return p
    found = shutil.which(name)
    if found:
        return Path(found)
    repo = _repo_bwc_bin()
    if repo:
        p = repo / name
        if p.is_file() and os.access(p, os.X_OK):
            return p
    return None


# Padding header: a chunk whose length is not a multiple of the max block
# size leaves a remainder block that MAX_SPLIT_DEPTH 0 forbids splitting, and
# that block is coded pathologically -- measured 2.46x the body's rmse with
# peaks at 3.6x QP on 54 % of channels. Padding up removes it; the true
# length must then travel with the stream so decode can trim.
_PAD_MAGIC = b"T2P1"
_PAD_HEADER = struct.Struct("<4sI")


def _resolve_cfg_dir() -> Path | None:
    env_dir = os.environ.get("BWC_CFG_DIR")
    if env_dir:
        p = Path(env_dir)
        if p.is_dir():
            return p
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "src" / "bwc" / "cfg"
        if candidate.is_dir():
            return candidate
    return None


ENCODER = _resolve_binary(_ENCODER_NAME)
DECODER = _resolve_binary(_DECODER_NAME)
CFG_DIR = _resolve_cfg_dir()

_AVAILABLE = ENCODER is not None and DECODER is not None and CFG_DIR is not None


_MAX_CHANNELS_RAWH2 = 65535  # uint16 header field


def _write_rawh2(path: Path, data: np.ndarray) -> None:
    """Write a (n_samples, n_channels) int16 array as RawH2 (see module docstring)."""
    if data.ndim != 2:
        raise ValueError(f"T.261 expects 2D (n_samples, n_channels) input, got shape {data.shape}")
    if data.dtype != np.int16:
        raise ValueError(f"T.261 expects int16 input, got dtype {data.dtype}")
    n_samples, n_channels = data.shape
    if n_samples <= 0:
        raise ValueError(f"T.261 requires at least one sample; got shape {data.shape}")
    if n_channels <= 0:
        raise ValueError(f"T.261 requires at least one channel; got shape {data.shape}")
    if n_channels > _MAX_CHANNELS_RAWH2:
        raise ValueError(
            f"T.261 RawH2 header caps n_channels at {_MAX_CHANNELS_RAWH2} (uint16); "
            f"got {n_channels}. Split the recording into channel groups upstream."
        )
    with path.open("wb") as f:
        f.write(_RAWH2_HEADER.pack(n_channels, 16))
        f.write(np.ascontiguousarray(data, dtype="<i2").tobytes())


def _read_rawh2(path: Path) -> np.ndarray:
    with path.open("rb") as f:
        header = f.read(_RAWH2_HEADER.size)
        n_channels, bit_depth = _RAWH2_HEADER.unpack(header)
        if bit_depth != 16:
            raise ValueError(
                f"RawH2 bit_depth {bit_depth} not supported (this codec is 16-bit only)"
            )
        raw = f.read()
    n_samples = len(raw) // (n_channels * 2)
    arr = np.frombuffer(raw, dtype="<i2").reshape(n_samples, n_channels)
    return np.ascontiguousarray(arr, dtype=np.int16)


def _bwc_timeout_s() -> float:
    """Wall-clock limit for one BWC subprocess call.

    This guards against a HUNG encoder, not a slow one, so it must not be
    tight enough to kill legitimate work. BWC costs roughly 20 s of compute
    per second of recording, so the wall time of one call scales with the
    chunk size AND with how contended the machine is: a 60 s chunk measured
    ~21 min on an idle box and blew the old hardcoded 1800 s under 15-way
    concurrency. Defaults to 2 h, which no healthy call approaches at the
    chunk sizes we use; override with COMPBENCH_T261_TIMEOUT_S.
    """
    import os

    raw = os.environ.get("COMPBENCH_T261_TIMEOUT_S")
    if not raw:
        return 7200.0
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(
            f"COMPBENCH_T261_TIMEOUT_S must be a number of seconds, got {raw!r}"
        ) from exc
    if value <= 0:
        raise ValueError("COMPBENCH_T261_TIMEOUT_S must be positive")
    return value


class T261Codec(Codec):  # type: ignore[misc]  # numcodecs.abc.Codec is untyped
    """numcodecs.Codec wrapper around the BWC reference encoder/decoder.

    Lossy control:
        ``step_size_for_qp`` — overrides the preset's ``StepSizeForQP``.
            1.0 is lossless; > 1.0 triggers quantization (higher = coarser
            → higher CR, more distortion). Values around 1.5..8 span the
            useful lossy range for biosignals.
        ``max_abs_delta_qp`` — overrides ``MaxAbsDeltaQP``; enables per-block
            QP variation (0 = uniform, higher = more adaptive).

    Any additional ``extra_args`` are appended verbatim after the standard
    flags. Both `step_size_for_qp` and `max_abs_delta_qp` translate to
    ``--StepSizeForQP=X`` / ``--MaxAbsDeltaQP=X`` overrides on the CLI.
    """

    codec_id = "t261"

    def __init__(
        self,
        preset: str = "combinedPresetEEG_IndepChannel_lossless",
        bit_depth: int = 16,
        step_size_for_qp: float | None = None,
        max_abs_delta_qp: int | None = None,
        extra_args: tuple[str, ...] = (),
        progress_dir: str | Path | None = None,
        pad_to_block: int = 0,
    ) -> None:
        if not _AVAILABLE:
            raise RuntimeError(
                "BWC binaries not found. Build src/bwc/ (see containers/README.md "
                "or run `cmake -S src/bwc -B src/bwc/build && make -C src/bwc/build`) "
                "or set BWC_BIN_DIR to a directory containing EncoderApp/DecoderApp."
            )
        cfg_path = (CFG_DIR / f"{preset}.cfg") if CFG_DIR else None
        if cfg_path is None or not cfg_path.is_file():
            available = ", ".join(sorted(p.stem for p in (CFG_DIR or Path()).glob("*.cfg")))
            raise ValueError(f"BWC preset {preset!r} not found. Available: {available}")
        if int(bit_depth) != 16:
            raise ValueError(
                f"bit_depth={bit_depth} not supported by the RawH2 stopgap wrapper "
                f"(header hard-codes 16-bit samples). The pybind11 wrapper in Phase 2b "
                f"will honour 16-24 bpp per the T.261 spec."
            )
        self.pad_to_block = int(pad_to_block)
        self.preset = preset
        self.bit_depth = int(bit_depth)
        self.step_size_for_qp = float(step_size_for_qp) if step_size_for_qp is not None else None
        self.max_abs_delta_qp = int(max_abs_delta_qp) if max_abs_delta_qp is not None else None
        self.extra_args = tuple(extra_args)
        self.progress_dir = Path(progress_dir) if progress_dir is not None else None
        self._cfg_path = cfg_path

    def _build_overrides(self) -> list[str]:
        """CLI arg list assembled from lossy knobs + user extras."""
        args: list[str] = []
        if self.step_size_for_qp is not None:
            args.append(f"--StepSizeForQP={self.step_size_for_qp}")
        if self.max_abs_delta_qp is not None:
            args.append(f"--MaxAbsDeltaQP={self.max_abs_delta_qp}")
        args.extend(self.extra_args)
        return args

    def get_config(self) -> dict[str, Any]:
        return {
            "id": self.codec_id,
            "preset": self.preset,
            "bit_depth": self.bit_depth,
            "step_size_for_qp": self.step_size_for_qp,
            "max_abs_delta_qp": self.max_abs_delta_qp,
            "extra_args": list(self.extra_args),
            "pad_to_block": self.pad_to_block,
        }

    def _run_bwc(
        self,
        cmd: list[str],
        scratch_root: Path,
        phase: str,
    ) -> None:
        """Run BWC binary with stdout/stderr streamed to on-disk log files.

        The log files are `<scratch_root>/<phase>.stdout.log` and
        `<phase>.stderr.log`. They exist as long as `scratch_root` exists —
        callers pin `scratch_root` via a TemporaryDirectory (or the
        `progress_dir=` init arg, which keeps the dir around for
        inspection). While the process is running, a separate observer can
        `tail -f` those files to compute an ETA — see
        `compbench t261-progress <scratch_root>`.

        On non-zero exit we read the tail of stderr into the exception
        message so callers still get a meaningful error.
        """
        scratch_root.mkdir(parents=True, exist_ok=True)
        stdout_path = scratch_root / f"{phase}.stdout.log"
        stderr_path = scratch_root / f"{phase}.stderr.log"
        with stdout_path.open("wb") as f_out, stderr_path.open("wb") as f_err:
            proc = subprocess.Popen(cmd, stdout=f_out, stderr=f_err)
            try:
                proc.wait(timeout=_bwc_timeout_s())
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                raise
        if proc.returncode != 0:
            tail = stderr_path.read_text(errors="replace")[-2000:]
            raise RuntimeError(f"BWC {phase} failed (rc={proc.returncode}):\n{tail}")

    def _make_scratch(self, kind: str) -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
        """Return (path, tempdir_handle-or-None). If `progress_dir` was set,
        the scratch lives there (persistent, inspectable); otherwise a
        TemporaryDirectory that must be kept alive by the caller.
        """
        if self.progress_dir is not None:
            # Persistent, unique-per-call subdir. `mkdtemp` gives us the
            # collision-free naming without touching tempfile internals.
            self.progress_dir.mkdir(parents=True, exist_ok=True)
            path = Path(tempfile.mkdtemp(prefix=f"{kind}-", dir=self.progress_dir))
            return path, None
        td = tempfile.TemporaryDirectory(prefix=f"t261-{kind}-")
        return Path(td.name), td

    def encode(self, buf: Any) -> bytes:
        data = np.asarray(buf)
        n_true = data.shape[0]
        pad = 0
        if self.pad_to_block > 1:
            rem = n_true % self.pad_to_block
            if rem:
                pad = self.pad_to_block - rem
                # MIRROR extension. This choice is the whole point, measured
                # on 1 s of MEArec NP1 at QP 5.0 (tail = the ragged final
                # block, body = everything before it):
                #
                #   extension      max|e|  n>2QP  tail rmse  body rmse
                #   unpadded           18    488     3.4956     1.4202
                #   replicate          18    488     3.4956     1.4202
                #   mirror              8      0     1.4186     1.4202
                #   zero               18    536     3.5166     1.4202
                #
                # Replicating is bit-identical to not padding at all, which
                # is how we know BWC already extends by repeating the last
                # sample. That appends a DC step, so the final block is half
                # signal and half constant -- which the DCT codes badly, and
                # it dumps the error onto the real samples: 2.46x the body's
                # rmse with peaks at 3.6x QP on 54 % of channels. Zeros are
                # worse (bigger step). Mirroring has no discontinuity, and
                # the tail then matches the body exactly.
                # `symmetric` rather than a hand-rolled reverse slice: it is
                # correct for pad >= n_true (a short final chunk), where a
                # slice would silently produce too few samples and leave the
                # length not a multiple of the block -- defeating the point.
                data = np.pad(data, ((0, pad), (0, 0)), mode="symmetric")
        scratch, td = self._make_scratch("enc")
        try:
            in_path = scratch / "input.raw"
            bs_path = scratch / "output.bwc"
            _write_rawh2(in_path, data)
            _, n_channels = data.shape
            cmd = [
                str(ENCODER),
                "-c",
                str(self._cfg_path),
                f"--InputFile={in_path}",
                f"--InputBitDepth={self.bit_depth}",
                f"--InputNumChannels={n_channels}",
                f"--BitstreamFile={bs_path}",
                "--FileFormat=RawH2",
                *self._build_overrides(),
            ]
            self._run_bwc(cmd, scratch, phase="encode")
            bitstream = bs_path.read_bytes()
            if pad:
                # The decoder returns whatever length it was given, so the
                # true sample count has to travel with the stream. Streams
                # without the magic decode exactly as before.
                return _PAD_HEADER.pack(_PAD_MAGIC, n_true) + bitstream
            return bitstream
        finally:
            if td is not None:
                td.cleanup()

    def decode(self, buf: Any, out: np.ndarray | None = None) -> np.ndarray:
        data_bytes = bytes(buf)
        n_true: int | None = None
        if data_bytes[: len(_PAD_MAGIC)] == _PAD_MAGIC:
            _, n_true = _PAD_HEADER.unpack_from(data_bytes, 0)
            data_bytes = data_bytes[_PAD_HEADER.size :]
        scratch, td = self._make_scratch("dec")
        try:
            bs_path = scratch / "input.bwc"
            out_path = scratch / "output.raw"
            bs_path.write_bytes(data_bytes)
            cmd = [
                str(DECODER),
                f"--BitstreamFile={bs_path}",
                f"--OutputFile={out_path}",
                "--FileFormat=RawH2",
            ]
            self._run_bwc(cmd, scratch, phase="decode")
            arr = _read_rawh2(out_path)
        finally:
            if td is not None:
                td.cleanup()
        if n_true is not None:
            arr = arr[:n_true]
        if out is not None:
            out[...] = arr
            return out
        return arr


# Register with numcodecs's global registry so any Zarr/consumer can decode.
if _AVAILABLE:
    register_codec(T261Codec)

    @register
    class T261Adapter(CodecAdapter):
        """T.261 / H.BWC (subprocess stopgap)."""

        name: ClassVar[str] = "t261"

        def __init__(
            self,
            preset: str = "combinedPresetEEG_IndepChannel_lossless",
            bit_depth: int | str = 16,
            step_size_for_qp: float | str | None = None,
            max_abs_delta_qp: int | str | None = None,
        ) -> None:
            step = float(step_size_for_qp) if step_size_for_qp not in (None, "", "None") else None
            delta = int(max_abs_delta_qp) if max_abs_delta_qp not in (None, "", "None") else None
            super().__init__(
                preset=preset,
                bit_depth=int(bit_depth),
                step_size_for_qp=step,
                max_abs_delta_qp=delta,
            )
            self._preset = preset
            self._bit_depth = int(bit_depth)
            self._step_size_for_qp = step
            self._max_abs_delta_qp = delta

        @property
        def lossy(self) -> bool:  # type: ignore[override]
            # Explicit QP override always wins; otherwise the preset name is
            # the source of truth (`_lossless` suffix = lossless).
            if self._step_size_for_qp is not None and self._step_size_for_qp > 1.0:
                return True
            return "_lossless" not in self._preset

        def make_codec(self) -> Codec:
            return T261Codec(
                preset=self._preset,
                bit_depth=self._bit_depth,
                step_size_for_qp=self._step_size_for_qp,
                max_abs_delta_qp=self._max_abs_delta_qp,
            )

        def describe(self) -> dict[str, Any]:
            """Extend the base description with BWC binary + config provenance.

            Reproducibility (R2-H6): a manifest with just `preset` name is
            insufficient — two runs against different BWC checkouts could
            produce different bitstreams with no way to tell from the
            manifest. We capture the BWC git SHA, the encoder version banner,
            and the resolved encoder/decoder paths.
            """
            info = super().describe()
            info["bwc"] = {
                "bwc_git_sha": _bwc_git_sha(),
                "encoder_version": _bwc_encoder_version(),
                "encoder_path": str(ENCODER) if ENCODER else None,
                "decoder_path": str(DECODER) if DECODER else None,
                "cfg_dir": str(CFG_DIR) if CFG_DIR else None,
                "cfg_sha256": _cfg_sha256(self._preset),
            }
            return info


def _cfg_sha256(preset: str) -> str | None:
    """SHA-256 of the preset .cfg actually used, so candidate identity is
    content rather than a filename.

    `BWC_CFG_DIR` lets candidate cfgs live outside the BWC checkout, and it
    is process-global: two sweeps can resolve the same `preset=` name to
    different files, and an edited candidate keeps its name. Recording only
    `preset` and `cfg_dir` cannot distinguish either case, which would make
    a profile-search result unattributable to the config that produced it.
    """
    if CFG_DIR is None:
        return None
    path = CFG_DIR / f"{preset}.cfg"
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


_BWC_SHA_CACHE: str | None = None


def _bwc_git_sha() -> str | None:
    """Resolve the git SHA of the BWC checkout that produced ENCODER.

    Cached at process level — the SHA doesn't change during a sweep, and
    at 336 T.261-heavy cells one `git rev-parse` each is otherwise ~1 s of
    pointless fork/exec (round-2 R4-M2 symmetry with _BWC_VERSION_CACHE).
    """
    global _BWC_SHA_CACHE
    if _BWC_SHA_CACHE is not None:
        return _BWC_SHA_CACHE
    if ENCODER is None:
        return None
    # ENCODER is typically <bwc_root>/bin/release/EncoderApp → parent[2] = bwc root
    try:
        bwc_root = ENCODER.resolve().parents[2]
        out = subprocess.check_output(
            ["git", "-C", str(bwc_root), "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3,
        )
        _BWC_SHA_CACHE = out.strip() or None
        return _BWC_SHA_CACHE
    except (subprocess.SubprocessError, FileNotFoundError, IndexError):
        return None


_BWC_VERSION_CACHE: str | None = None


def _bwc_encoder_version() -> str | None:
    """Best-effort BWC version identifier.

    The encoder's runtime banner ("Biomedical Waveform Codec (BWC),
    encoder ver. N.M") only prints during actual encode; too expensive
    to trigger at import. We use `git describe --tags` on the BWC
    checkout instead — that returns e.g. `BWC-6.0-2-g34c2a2a` which
    identifies both the tagged version and any post-tag drift.
    """
    global _BWC_VERSION_CACHE
    if _BWC_VERSION_CACHE is not None:
        return _BWC_VERSION_CACHE
    if ENCODER is None:
        return None
    try:
        bwc_root = ENCODER.resolve().parents[2]
        out = subprocess.check_output(
            ["git", "-C", str(bwc_root), "describe", "--tags", "--always"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3,
        )
        _BWC_VERSION_CACHE = out.strip() or None
        return _BWC_VERSION_CACHE
    except (subprocess.SubprocessError, FileNotFoundError, IndexError):
        return None
