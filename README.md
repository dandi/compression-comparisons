# compression-comparisons

Turnkey benchmark for compression of biomedical waveform data, comparing the
newly-standardised **ITU-T T.261 / ISO/IEC 23003-8** ("H.BWC") codec against
the codec set evaluated in Buccino et al. 2023
([J Neural Eng, 10.1088/1741-2552/acf5a4](https://doi.org/10.1088/1741-2552/acf5a4)).

**Status:** Phase 0 scaffolding — CLI + one codec (blosc-zstd) + con-duct wiring +
smoke test. See [`.specify/specs/t261-benchmark-plan.md`](.specify/specs/t261-benchmark-plan.md)
for the full design.

## Quickstart

```bash
# One-off dev install into a uv-managed venv:
uv venv && source .venv/bin/activate
uv pip install -e '.[devel]'

# All tests, lint, type-check via tox:
tox                  # everything
tox -e py311         # just unit tests on py3.11
tox -e integration   # end-to-end (needs `duct` on PATH)
tox -e lint          # ruff
tox -e type          # mypy
```

## One-command smoke

```bash
make smoke           # < 2 min: MEArec-tiny → duct compbench run → aggregator
```

## Layout

- `src/compbench/` — Python package: CLI, codecs, metrics, pipeline, report.
- `src/bwc/` — upstream ITU-T T.261 / H.BWC reference software (datalad subdataset;
  Clear BSD; upstream `https://vcgit.hhi.fraunhofer.de/vceg-sw/bwc`). Never patched
  in-tree — see §4.1a of the plan.
- `src/t261_numcodecs/` — (Phase 2) Python wrapper that builds against `../bwc/`.
- `containers/` — Dockerfiles derived from AIND's ephys-pipeline images; work with
  docker, podman, and (via `apptainer pull docker://…`) singularity/apptainer on HPC.
- `configs/` — dataset / codec / profile YAMLs. Add datasets by dropping a YAML;
  no Python edits needed.
- `.specify/specs/` — design docs.

## License

MIT for our code (this repo). The vendored `src/bwc/` reference software is
Clear BSD (Fraunhofer + Dolby). Note: T.261 has an explicit *no patent grant*
clause — flag to commercial downstream users.
