"""End-to-end Snakemake run on the smoke profile.

Skipped if `snakemake`, `duct`, or `compbench` are not on PATH.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

SNAKEMAKE = shutil.which("snakemake")
DUCT = shutil.which("duct")
COMPBENCH = shutil.which("compbench")

pytestmark = pytest.mark.integration


@pytest.mark.ai_generated
@pytest.mark.skipif(SNAKEMAKE is None, reason="`snakemake` not on PATH")
@pytest.mark.skipif(DUCT is None, reason="`duct` not on PATH")
@pytest.mark.skipif(COMPBENCH is None, reason="`compbench` not on PATH")
@pytest.mark.timeout(120)
def test_snakemake_runs_smoke_profile(tmp_path: Path) -> None:
    assert SNAKEMAKE and DUCT and COMPBENCH
    repo_root = Path(__file__).resolve().parents[2]
    snakefile = repo_root / "src" / "compbench" / "pipeline" / "Snakefile"

    # Build an inline profile: 1 dataset x 2 codec configs = 2 cells.
    import yaml

    profile = {
        "name": "smoke-int",
        "datasets": ["synthetic:duration_s=0.2,sample_rate_hz=1000,n_channels=2,seed=0"],
        "codecs": [
            {"codec": "blosc-zstd", "params": {"level": 3, "shuffle": "byte"}},
            {"codec": "lz4", "params": {"acceleration": 1}},
        ],
    }
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(yaml.safe_dump(profile))

    results_dir = tmp_path / "results"
    proc = subprocess.run(
        [
            SNAKEMAKE,
            "-s",
            str(snakefile),
            "--configfile",
            str(profile_path),
            "--config",
            f"results_dir={results_dir}",
            "--cores",
            "2",
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert proc.returncode == 0, (
        f"snakemake failed:\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )

    report = results_dir / "report.parquet"
    assert report.exists(), f"report missing; dir: {list(results_dir.iterdir())}"

    # Every cell dir should have metrics.json + duct-info.json.
    cell_dirs = [d for d in results_dir.iterdir() if d.is_dir()]
    assert len(cell_dirs) == 2, f"expected 2 cells; got {len(cell_dirs)}"
    for cd in cell_dirs:
        metrics = json.loads((cd / "metrics.json").read_text())
        assert metrics["round_trip_ok"] is True
        assert (cd / "duct-info.json").exists()
