"""Sanity checks for the container recipes.

We don't build the images here (they pull multi-GB base layers). Instead we
verify each Dockerfile parses, has the expected structure, and pins to the
same `AIND_TAG` — otherwise the three images could drift apart.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTAINERS = REPO_ROOT / "containers"


@pytest.mark.ai_generated
@pytest.mark.parametrize("name", ["compbench-base", "compbench-ks25", "compbench-ks4"])
def test_dockerfile_exists_and_readable(name: str) -> None:
    p = CONTAINERS / f"{name}.Dockerfile"
    assert p.exists(), f"missing Dockerfile: {p}"
    body = p.read_text()
    assert body.startswith(("#", "ARG", "FROM")), "must start with comment/ARG/FROM"


@pytest.mark.ai_generated
@pytest.mark.parametrize("name", ["compbench-base", "compbench-ks25", "compbench-ks4"])
def test_dockerfile_installs_compbench_and_duct(name: str) -> None:
    body = (CONTAINERS / f"{name}.Dockerfile").read_text()
    assert "pip install" in body
    assert "/opt/compbench" in body
    assert "con-duct" in body


@pytest.mark.ai_generated
@pytest.mark.parametrize("name", ["compbench-base", "compbench-ks25", "compbench-ks4"])
def test_dockerfile_has_sanity_check(name: str) -> None:
    body = (CONTAINERS / f"{name}.Dockerfile").read_text()
    assert "compbench --version" in body


@pytest.mark.ai_generated
@pytest.mark.parametrize("name", ["compbench-base", "compbench-ks25", "compbench-ks4"])
def test_dockerfile_builds_bwc_and_registers_t261(name: str) -> None:
    """Every container image must build BWC and prove `t261` shows up in
    `compbench list-codecs` at image-build time — otherwise Snakemake
    profiles that reference `t261` will fail inside the container."""
    body = (CONTAINERS / f"{name}.Dockerfile").read_text()
    # BWC sources copied and built.
    assert "COPY src/bwc /opt/bwc" in body, f"{name} does not copy src/bwc into the image"
    assert "cmake --build /opt/bwc/build" in body, f"{name} does not build BWC"
    assert "-Wno-restrict" in body, f"{name} missing GCC-12 false-positive workaround"
    # Environment points the wrapper at the built binaries + configs.
    assert "BWC_BIN_DIR=/opt/bwc/bin/release" in body
    assert "BWC_CFG_DIR=/opt/bwc/cfg" in body
    # Build-time proof that t261 registers.
    assert "compbench list-codecs | grep -qx t261" in body, (
        f"{name} does not assert t261 registration at build time"
    )


@pytest.mark.ai_generated
def test_all_dockerfiles_pin_same_aind_tag() -> None:
    tags = set()
    for name in ["compbench-base", "compbench-ks25", "compbench-ks4"]:
        body = (CONTAINERS / f"{name}.Dockerfile").read_text()
        m = re.search(r"^ARG AIND_TAG=(\S+)", body, re.MULTILINE)
        assert m, f"no AIND_TAG default in {name}"
        tags.add(m.group(1))
    assert len(tags) == 1, f"AIND_TAG default drifted across images: {tags}"


@pytest.mark.ai_generated
def test_all_dockerfiles_pull_from_aind_org() -> None:
    for name in ["compbench-base", "compbench-ks25", "compbench-ks4"]:
        body = (CONTAINERS / f"{name}.Dockerfile").read_text()
        assert "ghcr.io/allenneuraldynamics/" in body, f"{name} does not pull from AIND org"


@pytest.mark.ai_generated
def test_helper_scripts_present_and_executable() -> None:
    for script in ("build.sh", "to_apptainer.sh", "run.sh"):
        p = CONTAINERS / script
        assert p.exists(), f"missing {p}"
        assert p.stat().st_mode & 0o100, f"{p} is not executable"


@pytest.mark.ai_generated
def test_readme_mentions_all_runtimes() -> None:
    body = (CONTAINERS / "README.md").read_text().lower()
    for keyword in ["podman", "docker", "apptainer", "singularity"]:
        assert keyword in body, f"containers/README.md doesn't mention {keyword}"
