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


def _write_rawh2(path: Path, data: np.ndarray) -> None:
    """Write a (n_samples, n_channels) int16 array as RawH2 (see module docstring)."""
    if data.ndim != 2:
        raise ValueError(f"T.261 expects 2D (n_samples, n_channels) input, got shape {data.shape}")
    if data.dtype != np.int16:
        raise ValueError(f"T.261 expects int16 input, got dtype {data.dtype}")
    _, n_channels = data.shape
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


class T261Codec(Codec):  # type: ignore[misc]  # numcodecs.abc.Codec is untyped
    """numcodecs.Codec wrapper around the BWC reference encoder/decoder."""

    codec_id = "t261"

    def __init__(
        self,
        preset: str = "combinedPresetEEG_IndepChannel_lossless",
        bit_depth: int = 16,
        extra_args: tuple[str, ...] = (),
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
        self.preset = preset
        self.bit_depth = int(bit_depth)
        self.extra_args = tuple(extra_args)
        self._cfg_path = cfg_path

    def get_config(self) -> dict[str, Any]:
        return {
            "id": self.codec_id,
            "preset": self.preset,
            "bit_depth": self.bit_depth,
            "extra_args": list(self.extra_args),
        }

    def encode(self, buf: Any) -> bytes:
        data = np.asarray(buf)
        with tempfile.TemporaryDirectory(prefix="t261-enc-") as td:
            tmp = Path(td)
            in_path = tmp / "input.raw"
            bs_path = tmp / "output.bwc"
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
                *self.extra_args,
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if proc.returncode != 0:
                raise RuntimeError(f"BWC EncoderApp failed (rc={proc.returncode}):\n{proc.stderr}")
            return bs_path.read_bytes()

    def decode(self, buf: Any, out: np.ndarray | None = None) -> np.ndarray:
        data_bytes = bytes(buf)
        with tempfile.TemporaryDirectory(prefix="t261-dec-") as td:
            tmp = Path(td)
            bs_path = tmp / "input.bwc"
            out_path = tmp / "output.raw"
            bs_path.write_bytes(data_bytes)
            cmd = [
                str(DECODER),
                f"--BitstreamFile={bs_path}",
                f"--OutputFile={out_path}",
                "--FileFormat=RawH2",
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if proc.returncode != 0:
                raise RuntimeError(f"BWC DecoderApp failed (rc={proc.returncode}):\n{proc.stderr}")
            arr = _read_rawh2(out_path)
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
            **kw: Any,
        ) -> None:
            super().__init__(preset=preset, bit_depth=int(bit_depth), **kw)
            self._preset = preset
            self._bit_depth = int(bit_depth)

        @property
        def lossy(self) -> bool:  # type: ignore[override]
            # The .cfg name is the source of truth: `_lossless` suffix ⇒ lossless.
            return "_lossless" not in self._preset

        def make_codec(self) -> Codec:
            return T261Codec(preset=self._preset, bit_depth=self._bit_depth)
