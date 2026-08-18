"""Snakemake workflow package.

Users invoke via ``snakemake -s src/compbench/pipeline/Snakefile
--configfile configs/profiles/<profile>.yaml`` (or via ``make paper`` /
``make full`` for canned invocations).
"""

from __future__ import annotations

from compbench.pipeline.profile import Cell, Profile, expand_matrix, load_profile

__all__ = ["Cell", "Profile", "expand_matrix", "load_profile"]
