"""Round-2 R4-H2 regression: profile YAMLs must reject unknown keys.

The dataset-YAML loader was hardened in round 1; this covers the profile-YAML
loader (same class of typo bug: silent acceptance of `datasetss:` /
`codecs: [{codec: X, paramss: {...}}]`).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from compbench.pipeline.profile import load_profile


def _write(tmp_path: Path, cfg: dict) -> Path:
    p = tmp_path / "prof.yaml"
    p.write_text(yaml.safe_dump(cfg))
    return p


@pytest.mark.ai_generated
def test_top_level_unknown_key_rejected(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        {
            "name": "x",
            "datasets": ["synthetic:"],
            "codecs": [{"codec": "blosc-zstd"}],
            "typotypo_field": "oops",
        },
    )
    with pytest.raises(ValueError, match="unknown top-level key"):
        load_profile(p)


@pytest.mark.ai_generated
def test_codec_entry_unknown_key_rejected(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        {
            "name": "x",
            "datasets": ["synthetic:"],
            "codecs": [{"codec": "blosc-zstd", "paramss": {"level": 5}}],  # typo
        },
    )
    with pytest.raises(ValueError, match="unknown key"):
        load_profile(p)


@pytest.mark.ai_generated
def test_all_known_top_level_keys_accepted(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        {
            "name": "x",
            "datasets": ["synthetic:"],
            "codecs": [{"codec": "blosc-zstd", "params": {"level": 5}}],
            "results_dir": "/tmp/x",
            "container_base": "docker://foo",
        },
    )
    prof = load_profile(p)
    assert prof.name == "x"


@pytest.mark.ai_generated
def test_dict_source_also_validated() -> None:
    """--configfile passes a dict; the check must fire there too."""
    with pytest.raises(ValueError, match="unknown top-level key"):
        load_profile(
            {
                "name": "x",
                "datasets": ["synthetic:"],
                "codecs": [{"codec": "blosc-zstd"}],
                "bogus": True,
            }
        )
