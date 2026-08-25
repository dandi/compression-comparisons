"""Every codec config in a shipped profile must actually construct.

An invalid parameter is not caught until the cell runs, which on a real sweep
is hours in and after the scheduler has already committed to the matrix. A
`shuffle: bit` on a standalone codec cost 6 of 96 cells that way -- bit-shuffle
is a blosc feature, and nothing checked it up front.
"""

from pathlib import Path

import pytest
import yaml

from compbench import codecs as C
from compbench.pipeline.profile import expand_matrix, load_profile

PROFILES = sorted((Path(__file__).resolve().parents[2] / "configs" / "profiles").glob("*.yaml"))


@pytest.mark.parametrize("profile", PROFILES, ids=lambda p: p.stem)
def test_every_codec_config_constructs(profile: Path, tmp_path: Path) -> None:
    prof = load_profile(profile)
    invalid = []
    for cell in expand_matrix(prof, generated_dir=tmp_path):
        try:
            adapter = C.get(cell.codec)
        except Exception:
            # a codec that is not registered in THIS environment (wavpack
            # without its library, t261 without a built BWC) is an
            # environment gap, not a profile defect -- the sweep's own
            # startup check reports those with a fix hint
            continue
        try:
            adapter(**cell.codec_params)
        except Exception as exc:
            invalid.append(f"{cell.cell_id}: {exc}")
    assert not invalid, "invalid codec params:\n  " + "\n  ".join(invalid[:10])
