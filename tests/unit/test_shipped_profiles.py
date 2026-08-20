"""Every shipped profile must expand and every cell must be constructible.

This test exists because of a real failure: `shuffle: no` written bare in a
profile is a YAML 1.1 **boolean**, so PyYAML yields Python `False` rather
than the string `"no"`. That silently broke 13.6 % of both paper profiles —
144 and 336 cells — including the paper's single best NP1 general-purpose
configuration (lzma at high level with no shuffle, its Fig-6 headline
2.82). The axis had just been *added* to fix a reproduction gap, and half
of it was unrunnable from the moment it landed.

Nothing caught it: the profiles parsed, `expand_matrix` produced the right
cell count, and the failure would have appeared only when the first such
cell ran — mid-sweep, hours in. A profile that loads is not a profile that
runs.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml

from compbench.codecs import get as get_codec
from compbench.codecs import names as codec_names
from compbench.pipeline.profile import expand_matrix, load_profile

PROFILE_DIR = Path(__file__).resolve().parents[2] / "configs" / "profiles"
PROFILES = sorted(PROFILE_DIR.glob("*.yaml"))


def test_profiles_are_discovered():
    assert PROFILES, f"no profiles found under {PROFILE_DIR}"


@pytest.mark.parametrize("path", PROFILES, ids=lambda p: p.stem)
def test_profile_loads_and_expands(path):
    profile = load_profile(path)
    cells = list(expand_matrix(profile, generated_dir=tempfile.mkdtemp()))
    assert cells, f"{path.name} expanded to zero cells"


@pytest.mark.parametrize("path", PROFILES, ids=lambda p: p.stem)
def test_every_cell_constructs_its_codec(path):
    """The check that would have caught the YAML-boolean bug."""
    profile = load_profile(path)
    available = set(codec_names())
    failures = []
    for cell in expand_matrix(profile, generated_dir=tempfile.mkdtemp()):
        if cell.codec not in available:
            continue  # optional dependency absent on this host; Snakefile reports it
        try:
            get_codec(cell.codec)(**cell.codec_params)
        except Exception as exc:
            failures.append(f"{cell.cell_id}: {type(exc).__name__}: {exc}")
    assert not failures, (
        f"{len(failures)} cell(s) in {path.name} cannot construct their codec:\n  "
        + "\n  ".join(sorted(set(failures))[:10])
    )


@pytest.mark.parametrize("path", PROFILES, ids=lambda p: p.stem)
def test_no_yaml_boolean_shuffle_or_delta_values(path):
    """Catch the class of bug, not just this instance.

    `no`, `yes`, `on`, `off`, `y`, `n` are all YAML 1.1 booleans. Any of them
    unquoted in a codec parameter becomes True/False instead of a string.
    """
    raw = yaml.safe_load(path.read_text()) or {}
    offenders = []
    for i, entry in enumerate(raw.get("codecs") or []):
        for key, value in (entry.get("params") or {}).items():
            if isinstance(value, bool):
                offenders.append(f"codecs[{i}].params.{key} parsed as {value!r}")
    assert not offenders, (
        f"{path.name}: YAML parsed these codec params as booleans — quote them:\n  "
        + "\n  ".join(offenders)
    )


def test_shuffle_accepts_the_yaml_boolean_form():
    """Defence in depth: even unquoted, `no` must not silently mean False."""
    assert get_codec("lzma")(preset=9, shuffle=False).describe()["params"]["shuffle"] == "no"
    assert get_codec("lzma")(preset=9, shuffle="no").make_filters() == []


def test_shuffle_yes_is_rejected_with_a_useful_message():
    with pytest.raises(ValueError, match="did you mean"):
        get_codec("lzma")(preset=9, shuffle=True)


def test_paper_delta_cells_use_the_drivers_shuffle():
    """The paper's delta driver pins numcodecs codecs to BYTE shuffle.

    All 64 lzma rows in benchmark-lossless-delta.csv are high+byte. Running
    the `no` variant produces a number ~18 % above a row that does not exist.
    """
    for name in ("paper-real-np1-8", "paper-real-16"):
        raw = yaml.safe_load((PROFILE_DIR / f"{name}.yaml").read_text())
        for entry in raw["codecs"]:
            params = entry.get("params") or {}
            if entry["codec"] == "lzma" and params.get("delta", "no") != "no":
                assert params.get("shuffle") == "byte", (
                    f"{name}: lzma delta cell must use byte shuffle to match the "
                    f"paper's delta driver; got {params.get('shuffle')!r}"
                )
