# compression-comparisons

Turnkey benchmark for compression of biomedical waveform data, comparing the
newly-standardised **ITU-T T.261 / ISO/IEC 23003-8** ("H.BWC") codec against
the codec set evaluated in Buccino et al. 2023
([J Neural Eng, 10.1088/1741-2552/acf5a4](https://doi.org/10.1088/1741-2552/acf5a4)).

**Status (2026-09-30).** The Phase 1 reproduction is **complete**: 912 cells
(11 lossless codecs x 8 NP1 recordings x 4 preprocessing conditions x
parameter variants), 0 errors. Paired per recording against the paper's own
per-session results, the deviation is **median 0.017 %, max 5.39 %** over 288
gradeable cells (gate thresholds 2 % / 5 %); 287 of 288 are inside 5 %, and
the single miss is a cell where we compress *better* than the paper. Codec
**ranking reproduces 11/11**, including all best-shuffle choices, and the
paper's Fig-6 headline CRs match to four digits.

Spike-sorting evaluation is implemented and has been run: Kilosort 4 via
SpikeInterface against MEArec ground truth, at 600 s, plus the paper's Fig-14
waveform-feature criterion. `compbench.metrics.sorting` is no longer a
skeleton — earlier versions of this file said so, and that is out of date.

**T.261 versus the incumbent is a trade, not a win.** At their best operating
points WavPack Hybrid 2.25 bps gives CR 7.10 with +5 excess false-positive
units; T.261 QP 5.0 gives CR 8.58 with +19, both at lossless-parity unit
recovery. T.261 compresses ~21 % harder; WavPack keeps the detector quieter.

Three caveats that travel with every lossy claim here, all measured:

* **False positives are not resolvable at one run per arm.** WavPack's FP
  scatter across bps puts the error bar at ~17 units, and the headline
  difference above is 14. Two rate-neutral or fidelity-*improving* changes
  have since moved FP by +15 and +22 — so FP is monotone in distortion across
  large QP steps and emphatically not across small perturbations.
* **A T.261 defect is present in every result produced so far.** A 1 s chunk
  is not a whole number of 1024-sample blocks, and BWC extends the remainder
  by repeating the last sample; the resulting block codes at 2.46x the body's
  RMSE, peaking at 3.6x QP, on 54 % of channels. `--chunk-duration-s 1.024`
  removes it at -0.096 % CR (30000 x 1.024 = 30 x 1024 and 32000 x 1.024 =
  32 x 1024, both exact). Fixing it does **not** reduce false positives -- it
  raised them -- so it is a fidelity fix, not an FP fix.
* **The Fig-14 verdict at 600 s is unresolved.** T.261 QP 5.0 passes the
  paper's 10 % waveform line on a 100 s slice (p90 0.085) and fails at 600 s
  (0.120, on `peak_to_valley` at 60 um). If the 600 s figure holds, T.261 has
  no operating point that both passes the tolerance and beats WavPack's rate
  ceiling.

A ten-hypothesis search for T.261 profiles tuned to microelectrode data
tested seven and found **no usable compression gain**; see
[`.specify/specs/t261-profile-design-plan.md`](.specify/specs/t261-profile-design-plan.md),
which records each refutation and its mechanism. The one positive result is a
~39 % encode-time reduction that is *not* sorting-neutral.

See [`.specify/specs/t261-benchmark-plan.md`](.specify/specs/t261-benchmark-plan.md)
for the design and [`DEPLOY.md`](DEPLOY.md) for running it.

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

## Paper reproduction

```bash
# Portable (no wavpack — runs on any Linux):
make paper PROFILE=configs/profiles/paper.yaml

# Full paper matrix (needs wavpack-numcodecs installable):
pip install -e '.[audio]'
make paper PROFILE=configs/profiles/paper-with-wavpack.yaml
```

The completed reproduction used `configs/profiles/paper-real-np1-8-general.yaml`
(912 cells); `paper-real-np1-8.yaml` is the narrower gate matrix and
`paper-real-16.yaml` extends to all 16 recordings at full length. All use the
`datasets_matrix:` block, so adding a recording is one YAML entry.

Sorting evaluation is a separate pipeline — `sorting-eval-t261.yaml` for the
codec/QP sweep, `sorting-eval-t261-profiles.yaml` for the profile candidates.
Both need a GPU for Kilosort 4.

Note on `wavpack-numcodecs`: we run **0.2.3**, the paper used **0.1.3**. The
hybrid-mode flag changed in 0.1.4 (upstream `a812cb67`), so 0.1.3 silently
discards `level` — the paper's own `level=3` never took effect. The two are
rate-distortion equivalent at matched CR (median 1.2 %), but 0.1.3 reproduces
the paper's published lossy CR to within 0.9 % where 0.2.3 deviates up to
7.8 %. We keep 0.2.3 deliberately: 0.1.3's hybrid is broken and will not
install on Python 3.13.

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
  no Python edits needed. `configs/bwc-cfg/` holds the T.261 profile-search
  candidates alongside copies of every upstream preset, so `BWC_CFG_DIR` can
  point at one directory and resolve both (it is process-global, and pointing
  it at the candidates alone makes the stock presets unresolvable).
- `scripts/profile-search/` — the T.261 profile-search harnesses, kept so each
  recorded result can be re-run.
- `.specify/specs/` — design docs. `t261-benchmark-plan.md` is the overall
  design; `t261-profile-design-plan.md` carries the profile search and every
  measured refutation.

## License

MIT for our code (this repo). The vendored `src/bwc/` reference software is
Clear BSD (Fraunhofer + Dolby). Note: T.261 has an explicit *no patent grant*
clause — flag to commercial downstream users.
