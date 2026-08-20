"""Dataset paths in profiles must resolve independently of the sweep's CWD.

A paper sweep runs from the STAMPED study root — so that `sourcedata/...`
inside each dataset YAML resolves and results land in the study tree — but
profiles list datasets repo-root-relative (`configs/datasets/foo.yaml`) and
the study root has no `configs/`. This is the exact invocation DEPLOY §4
documents, and it used to fail.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from compbench.pipeline.profile import load_profile


@pytest.fixture
def repo(tmp_path):
    """A miniature tool repo: configs/{profiles,datasets}/ plus a study root."""
    (tmp_path / "repo/configs/datasets").mkdir(parents=True)
    (tmp_path / "repo/configs/profiles").mkdir(parents=True)
    (tmp_path / "study").mkdir()
    (tmp_path / "repo/configs/datasets/rec.yaml").write_text(
        yaml.safe_dump({"loader": "synthetic", "params": {"duration_s": 1.0}})
    )
    (tmp_path / "repo/configs/profiles/p.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "p",
                "datasets": ["configs/datasets/rec.yaml"],
                "codecs": [{"codec": "lzma", "params": {"preset": 6}}],
            }
        )
    )
    return tmp_path


def _chdir(path):
    prev = Path.cwd()
    os.chdir(path)
    return prev


def test_resolves_from_an_unrelated_cwd(repo):
    """The DEPLOY §4 case: profile in the tool repo, CWD is the study root."""
    prev = _chdir(repo / "study")
    try:
        prof = load_profile(repo / "repo/configs/profiles/p.yaml")
    finally:
        os.chdir(prev)
    assert Path(prof.datasets[0]).is_file()
    assert Path(prof.datasets[0]).name == "rec.yaml"


def test_cwd_relative_paths_still_win(repo):
    """Backwards compatibility: an existing CWD-relative path is left alone."""
    prev = _chdir(repo / "repo")
    try:
        prof = load_profile(repo / "repo/configs/profiles/p.yaml")
    finally:
        os.chdir(prev)
    assert prof.datasets[0] == "configs/datasets/rec.yaml"


def test_configfile_dict_needs_an_explicit_base_dir(repo):
    """Snakemake's --configfile drops the filename; base_dir carries it."""
    raw = yaml.safe_load((repo / "repo/configs/profiles/p.yaml").read_text())
    prev = _chdir(repo / "study")
    try:
        unanchored = load_profile(raw)
        anchored = load_profile(raw, base_dir=repo / "repo/configs/profiles")
    finally:
        os.chdir(prev)
    # Without the anchor the path is passed through untouched, so the loader
    # reports the path the user actually wrote rather than a guess.
    assert unanchored.datasets[0] == "configs/datasets/rec.yaml"
    assert Path(anchored.datasets[0]).is_file()


def test_uri_schemes_are_not_treated_as_paths(repo):
    raw = {
        "name": "p",
        "datasets": ["synthetic:duration_s=5.0,seed=0"],
        "codecs": [{"codec": "lzma"}],
    }
    prof = load_profile(raw, base_dir=repo / "repo/configs/profiles")
    assert prof.datasets[0] == "synthetic:duration_s=5.0,seed=0"


def test_absolute_paths_are_untouched(repo):
    target = repo / "repo/configs/datasets/rec.yaml"
    prof = load_profile(
        {"name": "p", "datasets": [str(target)], "codecs": [{"codec": "lzma"}]},
        base_dir=repo / "repo/configs/profiles",
    )
    assert prof.datasets[0] == str(target)


def test_unresolvable_path_is_passed_through_verbatim(repo):
    """So the loader's FileNotFoundError names what the user wrote."""
    prof = load_profile(
        {"name": "p", "datasets": ["configs/datasets/nope.yaml"], "codecs": [{"codec": "lzma"}]},
        base_dir=repo / "repo/configs/profiles",
    )
    assert prof.datasets[0] == "configs/datasets/nope.yaml"
