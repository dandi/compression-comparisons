"""Profile parsing + sweep-matrix expansion.

A profile YAML has:

    name: paper           # results directory suffix
    datasets:
      - configs/datasets/foo.yaml
      - synthetic:duration_s=5.0,seed=0
    codecs:
      - codec: blosc-zstd
        params: {level: 3, shuffle: byte}
      - codec: wavpack
        params: {level: 2}
      - codec: wavpack
        params: {level: 2, bps: 2.25}   # lossy

Hand-listing `datasets:` stops scaling at the paper's 16 recordings x N
preprocessing variants (48+ near-identical YAMLs). `datasets_matrix:`
cross-products a recording list with a preprocessing list instead::

    datasets_matrix:
      loader: aind-benchmark
      params: {start_s: 0.0, duration_s: 60.0}   # common to every cell
      recordings:
        - {label: ibl-CSHZAD026, path: sourcedata/.../CSHZAD026_2020-09-04_probe00}
        - {label: ibl-CSHZAD029, path: sourcedata/.../CSHZAD029_2020-09-09_probe00}
      preprocessing:
        - {label: raw}
        - {label: bp, steps: [{kind: bandpass, low_hz: 300, high_hz: 6000, order: 4}]}

`expand_matrix()` materialises one dataset YAML per (recording x
preprocessing) into `generated_dir` and treats them exactly like
hand-written ones — so the generated files stay readable, diffable, and
land in the results tree as provenance. `datasets:` and `datasets_matrix:`
may be used together; explicit entries come first.

`expand_matrix()` yields one `Cell` per (dataset x codec-config) pair, with
a stable, filesystem-safe `cell_id` derived from those two — the Snakefile
uses this ID as the directory name under `results/<profile>/`.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Cell:
    """One (dataset x codec x params) combination in the sweep matrix."""

    cell_id: str
    dataset_spec: str  # what compbench --input consumes
    codec: str  # what compbench --codec consumes
    codec_params: dict[str, Any] = field(default_factory=dict)
    dataset_label: str = ""  # short human-readable name
    codec_label: str = ""  # short human-readable name

    @property
    def codec_params_cli(self) -> str:
        """Serialise params as ``k=v,k=v`` for `compbench --codec-params`."""
        return ",".join(f"{k}={v}" for k, v in self.codec_params.items())


@dataclass
class Profile:
    name: str
    datasets: list[str]
    codecs: list[dict[str, Any]]
    datasets_matrix: dict[str, Any] | None = None

    def raw(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": self.name,
            "datasets": self.datasets,
            "codecs": self.codecs,
        }
        if self.datasets_matrix is not None:
            out["datasets_matrix"] = self.datasets_matrix
        return out


def load_profile(source: str | Path | dict[str, Any]) -> Profile:
    """Parse a profile from a YAML path or an already-parsed dict.

    Both entry points (Snakefile's ``--configfile`` and ``compbench``'s own
    ``--profile`` arg) share this validator so the schema check happens
    exactly once and the same error messages are raised in both cases.
    """
    if isinstance(source, dict):
        raw = source
        label = "<dict>"
    else:
        p = Path(source)
        label = str(p)
        with p.open() as f:
            raw = yaml.safe_load(f) or {}
    # Strict-key check (round-2 R4-H2): silent typos in profile YAMLs are the
    # same bug factory as in dataset YAMLs; a hand-authored `paper-real.yaml`
    # with `datasetss:` or `codes:` would silently produce an empty sweep.
    _allowed_top = {
        "name",
        "datasets",
        "datasets_matrix",
        "codecs",
        "results_dir",
        "container_base",
    }
    unknown = set(raw) - _allowed_top
    if unknown:
        raise ValueError(
            f"Profile {label}: unknown top-level key(s) {sorted(unknown)}. "
            f"Allowed: {sorted(_allowed_top)}."
        )
    name = raw.get("name")
    if not name:
        raise ValueError(f"Profile {label}: missing `name:`")
    datasets = raw.get("datasets") or []
    if not isinstance(datasets, list):
        raise ValueError(f"Profile {label}: `datasets:` must be a list")
    matrix = raw.get("datasets_matrix")
    if matrix is not None:
        _validate_datasets_matrix(matrix, label)
    if not datasets and matrix is None:
        raise ValueError(
            f"Profile {label}: needs a non-empty `datasets:` list, "
            f"a `datasets_matrix:` block, or both"
        )
    codecs = raw.get("codecs") or []
    if not isinstance(codecs, list) or not codecs:
        raise ValueError(f"Profile {label}: `codecs:` must be a non-empty list")
    _allowed_codec_keys = {"codec", "params"}
    for i, c in enumerate(codecs):
        if not isinstance(c, dict) or "codec" not in c:
            raise ValueError(f"Profile {label}: codecs[{i}] must be a dict with `codec:`")
        unknown = set(c) - _allowed_codec_keys
        if unknown:
            raise ValueError(
                f"Profile {label}: codecs[{i}] has unknown key(s) {sorted(unknown)}. "
                f"Allowed: {sorted(_allowed_codec_keys)} — did you mean `params:`?"
            )
    return Profile(
        name=str(name),
        datasets=[str(d) for d in datasets],
        codecs=list(codecs),
        datasets_matrix=matrix,
    )


_MATRIX_KEYS = {"loader", "params", "recordings", "preprocessing"}
_RECORDING_KEYS = {"label", "params"}
_PREPROC_KEYS = {"label", "steps"}


def _validate_datasets_matrix(matrix: Any, label: str) -> None:
    """Strict-key + shape validation for a `datasets_matrix:` block.

    Same rationale as the profile/dataset-YAML strict-key checks: at
    16 recordings x N preprocessing a silent typo (`recording:` for
    `recordings:`) yields a quietly-empty sweep rather than an error.
    """
    where = f"Profile {label}: datasets_matrix"
    if not isinstance(matrix, dict):
        raise ValueError(f"{where} must be a mapping")
    unknown = set(matrix) - _MATRIX_KEYS
    if unknown:
        raise ValueError(
            f"{where}: unknown key(s) {sorted(unknown)}. Allowed: {sorted(_MATRIX_KEYS)}."
        )
    if not matrix.get("loader"):
        raise ValueError(f"{where}: missing required `loader:`")
    if not isinstance(matrix.get("params", {}), dict):
        raise ValueError(f"{where}: `params:` must be a mapping")

    recordings = matrix.get("recordings")
    if not isinstance(recordings, list) or not recordings:
        raise ValueError(f"{where}: `recordings:` must be a non-empty list")
    seen_rec: set[str] = set()
    for i, rec in enumerate(recordings):
        if not isinstance(rec, dict):
            raise ValueError(f"{where}: recordings[{i}] must be a mapping")
        unknown = set(rec) - _RECORDING_KEYS
        if unknown:
            raise ValueError(
                f"{where}: recordings[{i}] has unknown key(s) {sorted(unknown)}. "
                f"Allowed: {sorted(_RECORDING_KEYS)} — per-recording loader args "
                f"go under `params:`."
            )
        rlabel = rec.get("label")
        if not rlabel:
            raise ValueError(f"{where}: recordings[{i}] missing `label:`")
        if not isinstance(rec.get("params", {}), dict):
            raise ValueError(f"{where}: recordings[{i}] `params:` must be a mapping")
        if str(rlabel) in seen_rec:
            raise ValueError(f"{where}: duplicate recording label {rlabel!r}")
        seen_rec.add(str(rlabel))

    # `preprocessing:` is optional — absent means a single raw variant.
    preprocs = matrix.get("preprocessing")
    if preprocs is None:
        return
    if not isinstance(preprocs, list) or not preprocs:
        raise ValueError(f"{where}: `preprocessing:` must be a non-empty list when present")
    seen_pre: set[str] = set()
    for i, pre in enumerate(preprocs):
        if not isinstance(pre, dict):
            raise ValueError(f"{where}: preprocessing[{i}] must be a mapping")
        unknown = set(pre) - _PREPROC_KEYS
        if unknown:
            raise ValueError(
                f"{where}: preprocessing[{i}] has unknown key(s) {sorted(unknown)}. "
                f"Allowed: {sorted(_PREPROC_KEYS)}."
            )
        plabel = pre.get("label")
        if not plabel:
            raise ValueError(f"{where}: preprocessing[{i}] missing `label:`")
        if str(plabel) in seen_pre:
            raise ValueError(f"{where}: duplicate preprocessing label {plabel!r}")
        seen_pre.add(str(plabel))
        steps = pre.get("steps")
        if steps is not None and not isinstance(steps, list):
            raise ValueError(f"{where}: preprocessing[{i}] `steps:` must be a list")


_SAFE_CHAR = re.compile(r"[^a-zA-Z0-9._-]")


def _slug(value: str, maxlen: int = 40) -> str:
    """Filesystem-safe slug — replaces unsafe chars, truncates."""
    s = _SAFE_CHAR.sub("_", value)
    return s[:maxlen].strip("_") or "x"


def _dataset_label(spec: str) -> str:
    """Short label — filename stem for a path, scheme for a URI, else slug."""
    if ":" in spec and not Path(spec).exists():
        scheme = spec.split(":", 1)[0]
        return _slug(scheme, 20)
    return _slug(Path(spec).stem, 30)


def _codec_label(codec: str, params: dict[str, Any]) -> str:
    """Short label — codec-name + hyphen-joined k=v pairs, hashed if too long."""
    if not params:
        return _slug(codec, 30)
    kv = "-".join(f"{k}={v}" for k, v in params.items())
    combined = f"{codec}-{kv}"
    if len(combined) <= 60:
        return _slug(combined, 60)
    # Too long — keep the codec name and hash the params for uniqueness.
    h = hashlib.sha256(kv.encode()).hexdigest()[:8]
    return _slug(f"{codec}-{h}", 30)


def _cell_id(dataset_label: str, codec_label: str) -> str:
    return f"{dataset_label}__{codec_label}"


def materialize_datasets_matrix(matrix: dict[str, Any], out_dir: str | Path) -> list[str]:
    """Write one dataset YAML per (recording x preprocessing); return their paths.

    Generating real files rather than passing dicts around keeps three
    properties we rely on at 300+ cell scale:

    * the Snakefile can hand `compbench run --input <path>` a plain string;
    * `datasets.load()` records `yaml_source` in provenance, so every
      `manifest.json` names the exact generated file that produced it;
    * a human can read, diff, and archive what actually ran.

    Writes are idempotent — re-running a sweep rewrites byte-identical
    files, so Snakemake's dependency graph is unaffected.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    loader = str(matrix["loader"])
    common = dict(matrix.get("params", {}))
    preprocs: list[dict[str, Any]] = matrix.get("preprocessing") or [{"label": "raw"}]

    paths: list[str] = []
    for rec in matrix["recordings"]:
        rec_params = dict(rec.get("params", {}))
        for pre in preprocs:
            # Per-recording params win over the matrix-wide defaults.
            params = {**common, **rec_params}
            cfg: dict[str, Any] = {"loader": loader, "params": params}
            steps = pre.get("steps")
            if steps:
                cfg["preprocessing"] = list(steps)
            name = f"{_slug(str(rec['label']), 60)}-{_slug(str(pre['label']), 20)}"
            path = out / f"{name}.yaml"
            text = (
                "# Generated by compbench from a profile's `datasets_matrix:` block.\n"
                "# Edit the profile, not this file — it is rewritten every sweep.\n"
                + yaml.safe_dump(cfg, sort_keys=False)
            )
            # Only touch the file when content changes, so mtime-based tools
            # don't see spurious updates on a resumed sweep.
            if not path.exists() or path.read_text() != text:
                path.write_text(text)
            paths.append(str(path))
    return paths


def expand_matrix(profile: Profile, generated_dir: str | Path | None = None) -> Iterator[Cell]:
    """Yield every (dataset x codec-config) cell in the profile.

    When the profile carries a `datasets_matrix:` block, `generated_dir`
    says where the expanded dataset YAMLs are written; it is required in
    that case (the caller knows the results directory, this function
    doesn't).
    """
    specs = list(profile.datasets)
    if profile.datasets_matrix is not None:
        if generated_dir is None:
            raise ValueError(
                "Profile uses `datasets_matrix:` but expand_matrix() was called "
                "without `generated_dir` — pass the directory the generated "
                "dataset YAMLs should be written to."
            )
        specs.extend(materialize_datasets_matrix(profile.datasets_matrix, generated_dir))

    seen: set[str] = set()
    for dspec in specs:
        dlabel = _dataset_label(dspec)
        for cfg in profile.codecs:
            codec_name = str(cfg["codec"])
            params = dict(cfg.get("params", {}))
            clabel = _codec_label(codec_name, params)
            cid = _cell_id(dlabel, clabel)
            if cid in seen:
                # Collision → hash-suffix to disambiguate.
                extra = hashlib.sha256(f"{dspec}|{codec_name}|{params}".encode()).hexdigest()[:6]
                cid = f"{cid}_{extra}"
            seen.add(cid)
            yield Cell(
                cell_id=cid,
                dataset_spec=dspec,
                codec=codec_name,
                codec_params=params,
                dataset_label=dlabel,
                codec_label=clabel,
            )
