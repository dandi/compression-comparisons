"""Unit tests for the profile parser + matrix expander."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from compbench.pipeline.profile import Profile, expand_matrix, load_profile


def _write_profile(tmp_path: Path, cfg: dict) -> Path:
    p = tmp_path / "prof.yaml"
    p.write_text(yaml.safe_dump(cfg))
    return p


@pytest.mark.ai_generated
def test_load_profile_basic(tmp_path: Path) -> None:
    p = _write_profile(
        tmp_path,
        {
            "name": "smoke",
            "datasets": ["synthetic:duration_s=1"],
            "codecs": [{"codec": "blosc-zstd", "params": {"level": 3}}],
        },
    )
    prof = load_profile(p)
    assert prof.name == "smoke"
    assert prof.datasets == ["synthetic:duration_s=1"]
    assert prof.codecs[0]["codec"] == "blosc-zstd"


@pytest.mark.ai_generated
def test_load_profile_missing_name(tmp_path: Path) -> None:
    p = _write_profile(tmp_path, {"datasets": ["synthetic:"], "codecs": [{"codec": "blosc-zstd"}]})
    with pytest.raises(ValueError, match="missing `name:`"):
        load_profile(p)


@pytest.mark.ai_generated
def test_load_profile_empty_datasets(tmp_path: Path) -> None:
    p = _write_profile(tmp_path, {"name": "x", "datasets": [], "codecs": [{"codec": "blosc-zstd"}]})
    with pytest.raises(ValueError, match="datasets"):
        load_profile(p)


@pytest.mark.ai_generated
def test_load_profile_codecs_must_have_codec_key(tmp_path: Path) -> None:
    p = _write_profile(
        tmp_path,
        {"name": "x", "datasets": ["synthetic:"], "codecs": [{"params": {"level": 3}}]},
    )
    with pytest.raises(ValueError, match="codecs"):
        load_profile(p)


@pytest.mark.ai_generated
def test_expand_matrix_cardinality() -> None:
    prof = Profile(
        name="x",
        datasets=["synthetic:duration_s=1", "synthetic:duration_s=2"],
        codecs=[
            {"codec": "blosc-zstd", "params": {"level": 3}},
            {"codec": "blosc-zstd", "params": {"level": 5}},
            {"codec": "lz4"},
        ],
    )
    cells = list(expand_matrix(prof))
    assert len(cells) == 2 * 3


@pytest.mark.ai_generated
def test_expand_matrix_cell_ids_are_unique() -> None:
    prof = Profile(
        name="x",
        datasets=["synthetic:duration_s=1", "synthetic:duration_s=2"],
        codecs=[
            {"codec": "blosc-zstd", "params": {"level": 3}},
            {"codec": "blosc-zstd", "params": {"level": 5}},
        ],
    )
    cells = list(expand_matrix(prof))
    ids = [c.cell_id for c in cells]
    assert len(ids) == len(set(ids)), f"duplicate cell_ids: {ids}"


@pytest.mark.ai_generated
def test_expand_matrix_cli_serialisation() -> None:
    prof = Profile(
        name="x",
        datasets=["synthetic:"],
        codecs=[{"codec": "blosc-zstd", "params": {"level": 3, "shuffle": "byte"}}],
    )
    cells = list(expand_matrix(prof))
    assert cells[0].codec_params_cli == "level=3,shuffle=byte"


@pytest.mark.ai_generated
def test_expand_matrix_dedupes_collisions_via_hash_suffix() -> None:
    # Two codec configs that could theoretically slug to the same label
    # if we truncated aggressively — construct explicitly to check the guard.
    prof = Profile(
        name="x",
        datasets=["synthetic:"],
        codecs=[
            {"codec": "blosc-zstd", "params": {"level": 3}},
            {"codec": "blosc-zstd", "params": {"level": 3, "shuffle": "byte"}},
        ],
    )
    cells = list(expand_matrix(prof))
    ids = [c.cell_id for c in cells]
    assert len(set(ids)) == len(ids)


@pytest.mark.ai_generated
def test_expand_matrix_cell_ids_are_filesystem_safe() -> None:
    prof = Profile(
        name="x",
        datasets=["synthetic:duration_s=1.5,sample_rate_hz=30000"],
        codecs=[{"codec": "blosc-zstd", "params": {"level": 3, "shuffle": "byte"}}],
    )
    for c in expand_matrix(prof):
        # No path separators, no shell metacharacters.
        assert "/" not in c.cell_id
        assert "\\" not in c.cell_id
        for bad in " '\"$&;|<>":
            assert bad not in c.cell_id, f"bad char {bad!r} in {c.cell_id!r}"
