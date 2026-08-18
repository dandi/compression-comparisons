"""Regression tests: shell-injection payloads in profile YAMLs must not execute.

Snakefile passes profile fields into shell rules; without `shlex.quote` a
malicious param value like `3' && rm -rf ~ && echo '` would run. We assert
the Snakefile source uses `shlex.quote` for every interpolated field and
that end-to-end the pipeline rejects (or safely quotes) such input.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SNAKEFILE = REPO_ROOT / "src" / "compbench" / "pipeline" / "Snakefile"


@pytest.mark.ai_generated
def test_snakefile_uses_shlex_quote_for_all_interpolated_fields() -> None:
    body = SNAKEFILE.read_text()
    assert "import shlex" in body, "Snakefile must `import shlex`"
    # Every field that flows from a profile YAML into the shell rule must be
    # quoted. We enforce the pattern (`shlex.quote(...)`) is used for the four
    # user-controlled inputs.
    for field in ("dataset_spec", "codec", "codec_params_cli"):
        assert f"shlex.quote(CELL_BY_ID[w.cell_id].{field})" in body, (
            f"Snakefile passes {field} through shell without shlex.quote"
        )


@pytest.mark.ai_generated
def test_snakefile_does_not_use_raw_field_interpolation_in_shell() -> None:
    body = SNAKEFILE.read_text()
    # The old dangerous patterns — either single or double-quoted raw
    # interpolation — must not be present anywhere.
    for bad in (
        "'{params.cell.dataset_spec}'",
        '"{params.cell.dataset_spec}"',
        "'{params.cell.codec_params_cli}'",
        '"{params.cell.codec_params_cli}"',
        "'{params.cell.codec}'",
    ):
        assert bad not in body, (
            f"Snakefile contains dangerous raw interpolation {bad!r} — "
            "profile YAMLs are untrusted (§9.5), must go through shlex.quote."
        )


@pytest.mark.ai_generated
def test_profile_expansion_survives_shell_metacharacters() -> None:
    """profile.py must slug shell metacharacters out of cell_id (defense in
    depth on top of shlex.quote — cell_id also appears in file paths)."""
    from compbench.pipeline.profile import Profile, expand_matrix

    prof = Profile(
        name="x",
        datasets=["synthetic:duration_s=1"],
        codecs=[{"codec": "blosc-zstd", "params": {"level": "3' && echo pwned && :'"}}],
    )
    cells = list(expand_matrix(prof))
    assert len(cells) == 1
    cid = cells[0].cell_id
    for bad in "&';|<>$`":
        assert bad not in cid, f"cell_id {cid!r} contains dangerous char {bad!r}"
