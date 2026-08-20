# compression-comparisons

Turnkey benchmark for compression of biomedical waveform data, comparing the
newly-standardised **ITU-T T.261 / ISO/IEC 23003-8** ("H.BWC") codec against
the codec set evaluated in Buccino et al. 2023
([J Neural Eng, 10.1088/1741-2552/acf5a4](https://doi.org/10.1088/1741-2552/acf5a4)).

**Status (2026-08-20).** Phase 1 reproduction verified against the paper's
own per-recording results: across 11 lossless codecs on CSHZAD026 at
matched conditions, **median |Δ| 0.06 %, max 2.5 %**. All 16 benchmark
recordings (523 GB) are local, and the full paper codec set — including
WavPack, WavPack Hybrid and FLAC — runs natively.

**Phase 3 is NOT complete.** `compbench.metrics.sorting` is a
contract-only skeleton: no spike-sorting or spike-train metric is
implemented yet, so every lossy claim currently rests on signal-level
distortion (RMSE / PRDN), which the paper's own data shows does not
predict sorting outcome. See
[`.specify/specs/t261-benchmark-plan.md`](.specify/specs/t261-benchmark-plan.md)
for the full design and
[`DEPLOY.md`](DEPLOY.md) for running it.

## Prerequisites

| Tool                    | Where to get it                     | Needed for                    |
| ----------------------- | ----------------------------------- | ----------------------------- |
| Python 3.11 – 3.13      | system / `uv python install`        | everything                    |
| `uv`                    | `pipx install uv`                   | recommended venv manager      |
| `duct` (con-duct)       | `pip install con-duct` (in `[devel]`) | `make smoke`, all Snakemake runs |
| `snakemake`             | `pip install snakemake` (in `[pipeline]`) | orchestrated sweeps      |
| C++20 compiler + cmake  | `apt-get install g++ cmake`         | building `src/bwc` (T.261)    |
| `wavpack-numcodecs`     | `pip install .[audio]`              | `paper-with-wavpack.yaml` (Ubuntu/manylinux glibc only) |
| `spikeinterface`        | `pip install .[ephys]`              | real ephys datasets (Phase 1+) |
| podman / docker         | system                              | containerised runs            |
| apptainer / singularity | system                              | HPC deployment                |

The `[devel]` extra installs everything needed for a laptop-dev workflow
except the C++ build. `pip install -e '.[devel,audio,ephys,pipeline]'` gets
you every optional codec and loader; `[audio]` will fail on hosts whose
glibc doesn't match a `wavpack-numcodecs` bundled wheel (works on Ubuntu
22.04/24.04, container images, manylinux CI).

## Quickstart

```bash
# One-off dev install into a uv-managed venv:
uv venv && source .venv/bin/activate
uv pip install -e '.[devel]'

# All tests, lint, type-check via tox:
tox                  # everything
tox -e py311         # unit tests on py3.11
tox -e integration   # end-to-end (needs `duct` on PATH)
tox -e lint          # ruff
tox -e type          # mypy strict
```

## One-command smokes

Two independent smoke targets with distinct failure modes — keep both, run
either first when debugging:

```bash
# 1. compbench CLI + con-duct + report aggregator; < 5 s.
make smoke               # duct compbench run … → metrics.json + duct-*.jsonl
                         # → compbench report → results/smoke/report.jsonl

# 2. Same but through Snakemake DAG; exercises the profile + orchestrator.
make snakemake-smoke     # snakemake … --configfile configs/profiles/smoke.yaml
```

Both use the synthetic-tiny dataset (`configs/datasets/synthetic-tiny.yaml`)
— no external data needed. The Snakefile fails fast (`WorkflowError`) if
the profile requests a codec that isn't installed on this host.

## Paper reproduction (in progress)

```bash
# Portable (no wavpack — runs on any Linux):
make paper PROFILE=configs/profiles/paper.yaml

# Full paper matrix (needs wavpack-numcodecs installable):
pip install -e '.[audio]'
make paper PROFILE=configs/profiles/paper-with-wavpack.yaml
```

The gate profile is `configs/profiles/paper-real-np1-8.yaml` (8 NP1
recordings x 4 preprocessing conditions x 44 codec configs = 1056 cells);
`paper-real-16.yaml` extends it to all 16 recordings at full length. Both
use the `datasets_matrix:` block, so adding a recording is one YAML entry.

## Layout

- `src/compbench/` — Python package: CLI, codecs, datasets, metrics, pipeline, report.
- `src/bwc/` — upstream ITU-T T.261 / H.BWC reference software (datalad subdataset;
  Clear BSD; upstream `https://vcgit.hhi.fraunhofer.de/vceg-sw/bwc`). Never patched
  in-tree — see §4.1a of the plan.
- `src/t261_numcodecs/` — (Phase 2b, not yet built) proper pybind11 wrapper. The
  current `t261` codec is a subprocess stopgap in `src/compbench/codecs/t261.py`.
- `containers/` — Dockerfiles derived from AIND's `ghcr.io/allenneuraldynamics/…`
  ephys-pipeline images. **Written but never built or run** — no number in
  this study was produced in a container. Reproducible per-codec images are
  planned as Phase 4.5.
- `configs/` — dataset / codec / profile YAMLs. Add datasets by dropping a YAML;
  no Python edits needed.
- `.specify/specs/` — design docs.

## License

MIT for our code (this repo). The vendored `src/bwc/` reference software is
Clear BSD (Fraunhofer + Dolby). Note: T.261 has an explicit *no patent grant*
clause — flag to commercial downstream users.
