# Plan — Extend Buccino et al. 2023 ephys compression benchmark to include ITU-T T.261 / ISO 23003-8 (H.BWC)

**Status:** draft for review
**Date:** 2026-08-17
**Author:** Yaroslav Halchenko + Claude (Opus 4.7, 1M context)
**Target repo:** `dandi/compression-comparisons` (this repo)

---

## 1. Executive summary

Buccino et al. 2023 (J Neural Eng, [10.1088/1741-2552/acf5a4](https://doi.org/10.1088/1741-2552/acf5a4)) established a benchmarking methodology for lossless and near-lossless compression of extracellular electrophysiology data, evaluating ~11 general-purpose and audio codecs on Neuropixels recordings. Their finding — WavPack (lossless) and WavPack-Hybrid (near-lossless) preserve spike-sorting fidelity at ~7× compression — is now the de-facto reference for the DANDI / SpikeInterface ecosystem.

In parallel, **ITU-T T.261** (a.k.a. H.BWC, twin-published as **ISO/IEC 23003-8 / MPEG-D Part 8**) was approved in **July 2026** as the first *standards-track* codec purpose-built for biomedical waveforms (EEG, ECG, EMG, and generic multichannel time-series at 500 Hz – 40 kHz, 16–24 bpp). **DICOM WG-32** work item **2022-09-A** is defining transfer syntaxes for it. The community currently has **no independent benchmark** comparing T.261 against the codecs Buccino et al. tested.

**This plan proposes a turnkey (single-command) framework that:**

1. Reproduces the Buccino et al. benchmark on arbitrary new datasets (any SpikeInterface-readable ephys, later ECG/EEG/EMG).
2. Adds T.261 as a first-class codec via a `numcodecs`-conformant wrapper, mirroring the `wavpack-numcodecs` pattern.
3. Produces the same evaluation profile (CR, ×RT throughput, RMSE, spike-sorting agreement, waveform-feature error) as machine-readable tables + published figures.
4. Handles T.261's licensing/redistribution constraints cleanly (fetch-at-build-time, not vendored).
5. Ships as containers (Docker + Apptainer) driven by Snakemake or Nextflow, so anyone — including DICOM WG-32 members — can drop in a new dataset and get a comparable report.

The deliverable is **not** a paper; it is infrastructure + a reference report. A paper follow-up is a downstream option, not a prerequisite.

---

## 2. Background — what already exists

### 2.1 The Buccino et al. 2023 framework (short review)

**Datasets tested:** 4 IBL NP1 recordings (from AWS Brain-Wide Map), 4+8 AIND NP1/NP2 pilot recordings, MEArec-simulated NP1 & NP2 (600 s each, 100 ground-truth units).

**Codecs (lossless):** `blosc-{lz4,lz4hc,zlib,zstd}`, `gzip`, `lz4`, `lzma`, `zlib`, `zstd` (all via `numcodecs`), plus **FLAC** and **WavPack** as audio codecs. Also filter variants: shuffling (none / byte / bit), 1D and 2D delta filters, chunk sizes 0.1 s / 1 s / 10 s, band-pass preprocessing.

**Codecs (lossy):** bit-truncation on top of `blosc-zstd`; **WavPack-Hybrid** at 2.25 – 6 bps.

**Metrics:** compression ratio (CR); compression speed and decompression speed as `×RT` (multiples of real-time on a 16-CPU AWS EC2 node); RMSE after 300–6000 Hz band-pass filter; spike-sorting accuracy/precision/recall with Kilosort 2.5 (ground-truth on simulated data, agreement-based curation on experimental); waveform-feature errors (peak-to-valley, FWHM, peak-to-trough).

**Infrastructure:** the paper's code lives in [`AllenNeuralDynamics/ephys-compression`](https://github.com/AllenNeuralDynamics/ephys-compression) — a collection of ~7 Python scripts (`benchmark-lossless.py`, `benchmark-lossless-delta.py`, `benchmark-lossless-preprocessing.py`, `benchmark-lossy-{sim,exp}.py`, `generate-gt-neuropixels-data.py`, `prepare_data_for_compression.py`). **No orchestration, no container, no single entry point, S3 bucket hard-coded.** Zarr I/O uses a SpikeInterface Zarr backend that landed upstream.

**Key reusable spin-offs:**

- [`AllenNeuralDynamics/wavpack-numcodecs`](https://github.com/AllenNeuralDynamics/wavpack-numcodecs) — the reference pattern for wrapping a C codec as a `numcodecs.Codec` usable inside Zarr. **This is the template for a T.261 wrapper.**
- [`AllenNeuralDynamics/aind-ephys-hybrid-benchmark`](https://github.com/AllenNeuralDynamics/aind-ephys-hybrid-benchmark) — newer, Nextflow + Docker, single-command entry point, but only supports WavPack. **This is the template for the orchestration layer.**

### 2.2 The ITU-T T.261 / ISO 23003-8 codec

| Facet                       | Value                                                                                                                                                                                                                                                                                                       |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Names                       | ITU-T Recommendation **T.261** (informally *H.BWC* — "Biomedical Waveform Coding"); ISO/IEC 23003-8; MPEG-D Part 8                                                                                                                                                                                          |
| Approved                    | July 2026                                                                                                                                                                                                                                                                                                   |
| Study group                 | ITU-T SG21 Q6 (formerly VCEG); joint with ISO/IEC JTC1/SC29/WG6 (MPEG Audio)                                                                                                                                                                                                                                |
| Primary editor              | ETRI (Electronics and Telecommunications Research Institute, Korea)                                                                                                                                                                                                                                         |
| Scope                       | Interoperable, flexible, lossy / near-lossless / lossless coding of biomedical & general multichannel waveforms                                                                                                                                                                                             |
| Bit depth                   | 16–24 bps                                                                                                                                                                                                                                                                                                   |
| Sample rate                 | 500 – 2 000 Hz clinical, up to 40 000 Hz research                                                                                                                                                                                                                                                           |
| Features                    | Multi-channel, mixed sample rates, independent & joint channel coding, blocking + indexing for selective random access                                                                                                                                                                                      |
| DICOM adoption              | WG-32 work item **2022-09-A** — new transfer syntaxes defined in DICOM Sup 253                                                                                                                                                                                                                              |
| Reference software           | **Publicly cloneable** at [`https://vcgit.hhi.fraunhofer.de/vceg-sw/bwc`](https://vcgit.hhi.fraunhofer.de/vceg-sw/bwc) under the **Clear BSD** license. Created 2025-01-09, 191 commits, 7 tagged releases as of 2026-08. Same Fraunhofer HHI GitLab that hosts JVET's VTM/HM/JM. No ITU membership required. |
| Specification PDF            | **Not yet in the public ITU-T database** as of 2026-08-18 — `https://www.itu.int/rec/T-REC-T.261` returns nothing. Publication lag from July 2026 approval is normal for ITU-T; expect it to appear over time. Not on the critical path — the reference software is our primary source. |

**Implication for our benchmark:** vendoring is straightforward. Pin `vceg-sw/bwc` as a git submodule (or a fetched tag inside `pyproject.toml`'s build backend) and produce a normal `manylinux` wheel of `t261-numcodecs` that can go to PyPI. The ITU-T specification PDF itself is a separate concern (publication lag; requires an ITU account for free download, membership for TIES-gated drafts), but the *code* is unencumbered.

### 2.3 Reference-software codebase review (verified 2026-08-17 at tag `BWC-6.0`)

The reference sources cloned to `src/bwc/` were reviewed and built end-to-end. Findings that shape §4.2 and §5-Phase-2 below:

**Build shape.** 100% **C++20**, no C, no assembly (SSE 4.1 via compiler flag only). ~46 `.cpp` + ~90 `.h` files. Zero third-party build deps — only the C++ standard library. CMake builds three static libs (`CommonLib`, `EncLib`, `DecLib`) plus two CLIs (`EncoderApp`, `DecoderApp`).

**Build on Linux (GCC 12, 4 cores, ~50 s).** Configure fails initially with a `-Werror=restrict` false positive inside `std::string::operator+` in `EDFReader.h` (a known GCC-12 diagnostic bug; disappears on GCC 13+). One-flag fix: `cmake -DCMAKE_CXX_FLAGS="-Wno-restrict" …`. With that flag the build is clean.

**Smoke test — synthetic 4 ch × 30 s @ 1 kHz int16 in `RawH2` format, `combinedPresetEEG_IndepChannel_lossless.cfg`:**

| File          | Size      | Notes                                      |
| ------------- | --------- | ------------------------------------------ |
| `input.raw`   | 240 004 B | 4-byte header + 240 000 B data             |
| `output.bwc`  | 20 906 B  | encoder reported `compressionFactor 11.48` |
| `decoded.raw` | 240 004 B | **byte-exact match with input**            |

Encoder self-reports `bits/sample 1.39`, `SNR inf dB`, `PRD 0.000%`; decoder confirms "No encoder-decoder mismatch found". Lossless round-trip works out of the box.

**API surface — no flat C/C++ buffer API.** Public entry points are C++ classes (`Encoder::run()`, decoder frame loop) that read/write files via `std::ifstream`/`std::ofstream`. However, the I/O is abstracted behind pure-virtual `PacketWriteIf` / `PacketReadIf` interfaces, so file streams can be substituted with in-memory streams **without patching the codec core** — a ~200-300 LoC shim inside the wrapper. A cleaner alternative is a ~50-line upstream refactor exposing a flat `encode_buffer()` function; that path is worth trying as a friendly upstream PR after wrapper Phase 2 lands.

**Process-level globals** (four of them, all in `CommonLib`) — `g_cfg`, `g_logStream`, `g_retVal`, `g_traceCABAC`. `g_cfg` is the concerning one: it is set at the start of each encode/decode and read from the transform core. Consequence for the wrapper: hold a per-codec-instance mutex around each encode/decode; document that a single `T261` codec instance is not thread-safe. This is acceptable for the Zarr / numcodecs contract (single-threaded per instance), and Python's GIL serialises calls anyway.

**Config-file centrality.** `EncAppCfg` parses `.cfg` files (or command-line key=value pairs) and threads through all codec state. Wrapper strategy: accept codec parameters as a dict, serialise to the existing key=value format, parse once at `Codec.__init__`, keep the parsed `EncAppCfg`/`DecAppCfg` as opaque handles inside the pybind11 class. 23 stock `.cfg` presets under `cfg/` cover ECG/EEG/EMG in lossy/lossless × combined/independent-channel variants — those become the starting `configs/codecs/t261-*.yaml` presets.

**`manylinux` prospects: excellent.** No Qt, no X11, no downloaded data, no hard-coded paths. GCC ≥ 10 or Clang ≥ 12; SIMD is optional (`-DENABLE_SIMD=OFF`) so a portable fallback wheel is possible. `cibuildwheel` on `manylinux_2_28` should work with only the `-Wno-restrict` flag.

**License note.** Clear BSD (Fraunhofer + Dolby, 2022–2024). Explicit *no patent grant* clause — worth flagging to downstream commercial users, though academic/DANDI use is unaffected.

**Minor surprises worth remembering:**

- Encoder writes `<bitstream>.rec` (encoder-side reconstruction) as a side-effect during file-mode encode. In-memory streams avoid the litter.
- `RawH2` format = 2-byte `uint16 n_channels`, 2-byte `uint16 bit_depth`, interleaved `int16` samples LE. Undocumented in README but obvious from `BasicWavReader`.
- Sampling rate is optional metadata; lossless encode/decode works without it. Handy for pure Zarr-chunk use cases.

### 2.4 The Neuropixels benchmark's applicability to T.261's target domain

Buccino et al. tested at 30 kHz × 384 channels × 16-bit — comfortably inside T.261's *research* envelope (≤ 40 kHz, 16–24 bpp). ECG/EEG/EMG are inside T.261's *clinical* envelope. Our framework must therefore be **modality-agnostic**: the same pipeline should ingest NWB/Zarr/SpikeGLX (ephys) and EDF/BDF/MEF/DICOM-Waveform (clinical), even if we start with ephys.

---

## 3. Gap analysis — what's missing today

| Gap                                           | Current state                                              | What we need                                                                            |
| --------------------------------------------- | ---------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| T.261 exposed as a `numcodecs` codec          | Does not exist                                             | New `t261-numcodecs` package following `wavpack-numcodecs` conventions                  |
| One-command reproducible run                  | `ephys-compression` is ~7 scripts w/ hard-coded S3 bucket  | Snakemake or Nextflow DAG + Docker/Apptainer container                                  |
| Dataset-agnostic ingestion                    | Hard-coded to specific NP1/NP2 S3 keys                     | Config-driven; accept SpikeInterface-readable path, NWB, DANDI dandiset ID, EDF, BDF    |
| Fair T.261 tuning                             | N/A                                                        | Sweep same axes as WavPack: level, target bps, chunk size, channel-grouping strategy    |
| Clinical-modality metrics (beyond ephys)      | RMSE + spike-sorting only                                  | Add PRD/PRDN (ECG standard), band-limited RMSE per T.261 conformance test conditions    |
| Container reproducibility w/ closed-source SW | N/A                                                        | Multi-stage Dockerfile: stage 1 fetches T.261 tarball from local mount, stage 2 builds  |
| Result publication                            | CSVs in `results/` dir; matplotlib figures generated ad hoc | Machine-readable Parquet + interactive report (Quarto / Streamlit) + Zenodo deposit    |
| CI                                            | None                                                       | GitHub Actions matrix: lint + unit tests + a *tiny* end-to-end smoke run on synthetic data |
| DANDI integration                             | N/A                                                        | Optional `--dandi-id 000xxx` shortcut that pulls a subset via `dandi-cli` for evaluation |

---

## 4. Proposed architecture

```
compression-comparisons/                (this repo — datalad dataset, no-annex)
├── .specify/specs/                     design docs
│   └── t261-benchmark-plan.md          (this file)
├── src/
│   ├── bwc/                            git-clone of https://vcgit.hhi.fraunhofer.de/vceg-sw/bwc (T.261 ref SW, Clear BSD)
│   ├── compbench/                      Python package
│   │   ├── cli.py                      `compbench` CLI entry point (§4.1) — one experiment per invocation
│   │   ├── datasets/                   loaders: spikeinterface, nwb, dandi, edf, bdf, mearec
│   │   ├── codecs/                     numcodecs.Codec instances (wraps blosc, flac, wavpack, t261)
│   │   ├── metrics/                    CR, RMSE, PRD/PRDN, waveform features, sorting eval (correctness only)
│   │   ├── pipeline/                   Snakemake rules that shell out to `duct compbench …` per cell
│   │   └── report/                     Parquet aggregator (joins compbench outputs + con-duct .jsonl) + Quarto
│   └── t261_numcodecs/                 sub-package: numcodecs wrapper around ../bwc
├── containers/
│   ├── compbench-base.Dockerfile       FROM ghcr.io/allenneuraldynamics/aind-ephys-pipeline-base:si-0.103.0
│   │                                   adds: con-duct, compbench, t261-numcodecs, wavpack-numcodecs
│   ├── compbench-ks25.Dockerfile       FROM ghcr.io/…/aind-ephys-spikesort-kilosort25:si-0.103.0 + compbench (CPU)
│   └── compbench-ks4.Dockerfile        FROM ghcr.io/…/aind-ephys-spikesort-kilosort4:si-0.103.0 + compbench (CUDA)
├── configs/
│   ├── datasets/*.yaml                 one YAML per benchmark dataset (name, loader, params, ground-truth?)
│   ├── codecs/*.yaml                   one YAML per codec-config (name, params, lossy?, bps?)
│   └── profiles/{smoke,paper,full}.yaml sweep matrices; smoke = CI-friendly, paper = Buccino re-run, full = +T.261
├── results/                            per-run output tree; each cell writes both `metrics.json` and `.duct/*.jsonl`
├── tests/                              pytest, marked with @pytest.mark.ai_generated where applicable
├── Makefile                            top-level targets: `make smoke`, `make paper`, `make full`
├── pyproject.toml                      single source of truth for deps (extras: test, devel, ci)
├── tox.ini                             concentrates all lint/test config
└── README.md                           quick-start: `make smoke` → 5 min; `make full DATASET=my.yaml` → hours
```

### 4.1 Core CLI — the reusable primitive

Every operation the benchmark performs is exposed as one CLI invocation. This is the *only* interface Snakemake (or any other orchestrator, or a human debugging a single cell) calls into. It has no orchestration, no sweep logic, and no notion of "the benchmark" — it runs *one* codec against *one* input and writes *one* result blob.

Rationale:

- Decouples "what to measure" from "how to enumerate runs" — Snakemake, a shell loop, a CI matrix, and a manual reproduction all use the same primitive.
- Makes each cell trivially wrappable by `duct` (§4.3) for resource profiling.
- Lets external users (DICOM WG-32, DANDI ingest team) evaluate T.261 on their own data without touching Snakemake or Python.
- Every artifact is on disk after each cell — no in-memory pipeline state to lose.

Command surface (concrete, subject to review):

```bash
# The workhorse: encode + decode + eval in one shot, writes metrics.json + optional round-trip artifact
compbench run \
    --input   /data/session.nwb                      # path OR dandi://000409/sub-XX/... OR configs/datasets/foo.yaml
    --codec   t261                                   # registered numcodecs codec name
    --codec-params  level=3,bps=2.25,chunk_s=1.0    # k=v,... — codec-specific
    --preprocessing bandpass:300-6000               # optional; matches paper's preprocessing sweep
    --metrics cr,rmse,rmse_bp,waveform,sort:kilosort4  # comma-list; skips heavy ones if omitted
    --output-dir /results/run-XYZ/                   # metrics.json, round_trip.zarr (optional), logs
    --seed    42

# Lower-level primitives (used by `run`, also usable standalone)
compbench encode   --input …  --codec …  --output cell.zarr
compbench decode   --input cell.zarr  --output round_trip.raw
compbench eval     --original …  --reconstructed …  --metrics …  --output metrics.json

# Introspection
compbench list-codecs                   # everything importable via the numcodecs entry point
compbench list-datasets                 # loaders + example YAMLs
compbench describe-codec t261           # dump parameter schema (from the codec class)
```

Design constraints:

- **One process, one cell.** No forking of parallel runs inside `compbench run` — parallelism belongs to the orchestrator so con-duct measurements stay attributable.
- **Deterministic output layout.** Every run writes `metrics.json` + `manifest.json` (input hash, codec version, git SHA, config resolved to fully-qualified values). This is what the report aggregator joins on.
- **Fail loud.** Non-zero exit on any measurement failure; partial metrics never silently promoted.
- **No hidden state.** All parameters come from CLI flags or the referenced YAMLs; no `~/.compbench` config file.
- **Codec registration via entry points** (`numcodecs`-style). Third-party codec wheels (e.g. `t261-numcodecs`) become available automatically without editing `compbench`.

### 4.1a Relationship between `src/bwc/` and `src/t261_numcodecs/`

Two directories, two roles:

| Path                     | Role                                          | Origin                                            | Modified by us?                             |
| ------------------------ | --------------------------------------------- | ------------------------------------------------- | ------------------------------------------- |
| `src/bwc/`               | Upstream C++20 reference codec ("the engine") | Datalad subdataset of `vcgit.hhi.fraunhofer.de/vceg-sw/bwc`, pinned to tag `BWC-6.0` | **No.** Never patched in-tree. Any fix goes upstream as a PR.  |
| `src/t261_numcodecs/`    | Our Python wrapper package ("the adapter")    | Written by us                                      | Yes.                                        |

At build time, `src/t261_numcodecs/pyproject.toml` uses `scikit-build-core` to compile a Python extension module. The extension is built from:

- **Ours:** a small pybind11 C++ shim + an in-memory `PacketWriteIf` / `PacketReadIf` implementation (~200–300 LoC total) living under `src/t261_numcodecs/`.
- **Upstream:** the sources of `libCommonLib` / `libEncLib` / `libDecLib` referenced *by path* from `../bwc/source/Lib/…` — either compiled directly into our extension, or linked against static libs built from `../bwc/`.

The Python-side `numcodecs.Codec` subclass in `src/t261_numcodecs/t261_numcodecs/__init__.py` imports the extension and exposes `T261(preset=..., level=..., bps=...)`. The `numcodecs` entry point in `pyproject.toml` makes `compbench list-codecs` pick it up automatically.

Rationale for keeping them as two sibling directories rather than nesting `src/bwc/` under `src/t261_numcodecs/vendor/`:

- `src/bwc/` is a datalad subdataset — cleaner at the repo root of `src/` than buried in the wrapper package.
- Any *other* consumer in this repo (e.g. a benchmark script that shells out to `EncoderApp` for a sanity check) can also reference `src/bwc/` directly without going through the wrapper.
- The wrapper package is portable — if we later split `t261-numcodecs` into its own PyPI-published repo, we replace the `../bwc/` path reference with a git submodule at `vendor/bwc/` inside that repo. No other changes.

### 4.2 The T.261 `numcodecs` wrapper — key design points

- Mimic `wavpack-numcodecs`'s API surface: `codec = T261(level=..., bps=None, ...); zarr.array(x, compressor=codec)`.
- The reference software is already checked out at `src/bwc/` (upstream `https://vcgit.hhi.fraunhofer.de/vceg-sw/bwc`, pinned at tag `BWC-6.0` as of 2026-08-17). For distribution we convert this to a git submodule pinned at a released tag; both the wrapper and the vendored sources are permissively licensed (Clear BSD), so we ship a normal `manylinux` wheel to PyPI.
- Binding: **`pybind11`** — the ref-sw is C++20 through-and-through (no flat C API; see §2.3), so pybind11's C++ class binding + numpy buffer-protocol support are the natural fit. `cffi` would only add an extra C shim layer.
- Threading contract: hold a per-codec-instance `std::mutex` around each encode/decode to serialise access to the codec's process-level globals (`g_cfg`, `g_logStream`, `g_retVal`); document that a single `T261` codec instance is not internally thread-safe. Zarr's normal single-thread-per-instance usage and the Python GIL make this a non-issue in practice.
- I/O adapter: implement `PacketWriteIf` / `PacketReadIf` over `std::stringstream` to avoid patching the codec core; ~200-300 LoC of glue. Optional upstream contribution later: a flat `encode_buffer()` API in `EncLib` (~50 LoC).
- Register a `numcodecs` entry-point so any Zarr consumer (SpikeInterface, DANDI, pynwb, xarray-with-zarr) picks the codec up automatically after `pip install t261-numcodecs`.
- CI matrix: build against every tagged bwc release we support, so a bwc bump is a one-line submodule move + a CI pass.
- If the C++ API changes across bwc releases in ways that force wrapper edits, wrap each generation behind a `T261.protocol_version` selector rather than forking the wrapper.
- Compiler-flag pin: ship `-DCMAKE_CXX_FLAGS="-Wno-restrict"` in the wrapper's build config to sidestep a GCC-12 false-positive in `EDFReader.h` (disappears on GCC 13+; §2.3).

### 4.3 Execution wrapping — [con/duct](https://github.com/con/duct)

Every `compbench` invocation is wrapped in [`duct`](https://github.com/con/duct) (`pip install con-duct`) to collect resource-usage traces. Encode/decode ×RT throughput is *derived from* con-duct's wall-clock, not measured inside Python — this removes measurement code from the hot path and gives us a uniform record for every cell, including the T.261 native-code portions that Python can't introspect.

Invocation pattern used by every Snakemake rule:

```bash
duct \
    --output-prefix "{results_dir}/{cell_id}/duct-" \
    --sample-interval 0.5 \
    --report-interval 5 \
    compbench run \
        --input {input} --codec {codec} --codec-params '{params}' \
        --output-dir {results_dir}/{cell_id}
```

Fields we join back per cell:

| From `metrics.json` (compbench)       | From `duct-*.jsonl` (con-duct)                              |
| ------------------------------------- | ----------------------------------------------------------- |
| CR, RMSE, sort-accuracy, waveform-err | wall time, CPU %, peak RSS, peak VSZ, exit code             |
| input hash, codec version, git SHA    | sampling series (for cost-vs-time plots)                    |
| encode / decode phase timestamps      | subprocess tree (catches C-lib threads spawned by T.261/KS) |

Two consequences worth calling out:

- **×RT throughput becomes an orchestration-side computation:** `xrt = recording_duration_s / duct.wall_time_s`. `compbench` records recording duration in the manifest; the report aggregator does the division. This means the throughput metric is *comparable across codecs even when the codec spawns native threads* — which is exactly the WavPack / T.261 case that would have confounded a naive `time.perf_counter()` around a Python call.
- **CI cost of resource sampling is negligible.** 0.5 s sampling of a 30 s cell = 60 samples × a handful of psutil fields = well under 100 KB per cell.

If a user wants to bypass con-duct (debugging), they invoke `compbench` directly — the CLI's contract does not depend on being wrapped.

### 4.4 Pipeline orchestration — Snakemake around the CLI

Snakemake is the recommended DAG layer. Its job is narrow: enumerate the sweep matrix, materialise inputs, and shell out to `duct compbench run …` per cell.

Choice rationale (unchanged from earlier draft):

- Python-native → shares the config schema with the codec/metric modules.
- Cleaner interaction with SLURM / Kubernetes / cloud executors than raw scripts.
- `aind-ephys-hybrid-benchmark` uses Nextflow, which is fine, but adopting it forces a Groovy dependency and a JVM.
- Reversible: pipeline logic (Python functions + config) is portable across DAG engines; only the DAG file changes. If we later want a Nextflow variant for compatibility with `aind-ephys-hybrid-benchmark`, we translate ~1 file, not the whole repo.

A rule looks roughly like:

```python
rule run_cell:
    input:  lambda w: dataset_path(w.dataset)
    output: "results/{run}/{dataset}/{codec}/{cell_id}/metrics.json"
    params: cfg = lambda w: codec_config(w.codec, w.cell_id)
    threads: 1                     # parallelism at the DAG level, not inside the cell
    shell:
        """
        duct --output-prefix $(dirname {output})/duct- \
             --sample-interval 0.5 \
             compbench run \
                 --input {input} \
                 --codec {wildcards.codec} \
                 --codec-params '{params.cfg}' \
                 --output-dir $(dirname {output})
        """
```

Runner command shape (target):

```bash
make full \
  DATASET=configs/datasets/dandi-000409-subset.yaml \
  CODECS=configs/profiles/full.yaml \
  OUT=results/2026-08-17-run
```

The Makefile just resolves those variables and invokes `snakemake --cores N --use-conda …`.

### 4.5 Metric set (superset of Buccino et al.)

Correctness metrics live in `compbench` (`metrics.json`). Cost/throughput metrics come from con-duct (`duct-*.jsonl`) and are joined at report-aggregation time.

| Metric                | Source        | Applies to              | Notes                                                                              |
| --------------------- | ------------- | ----------------------- | ---------------------------------------------------------------------------------- |
| CR                    | compbench     | all                     | bytes_original / bytes_compressed                                                  |
| Encode / decode ×RT   | con-duct + manifest | all               | `recording_duration / duct.wall_time`; comparable across native-threaded codecs   |
| Peak RSS, mean CPU %  | con-duct      | all                     | resource envelope per phase; catches native-code hotspots the Python-side misses  |
| RMSE (raw)            | compbench     | lossy                   | full-band                                                                          |
| RMSE (band-filtered)  | compbench     | ephys lossy             | 300 – 6 000 Hz — Buccino et al.'s definition                                       |
| PRD, PRDN             | compbench     | ECG lossy               | standard clinical distortion metrics; required for T.261 ECG conformance           |
| Waveform features     | compbench     | ephys lossy             | peak-to-valley, FWHM, peak-to-trough — Buccino et al.'s definitions                |
| Spike-sorting eval    | compbench     | ephys lossy             | Kilosort 4 (was 2.5 in paper — upgrade); accuracy/precision/recall vs GT or vs raw |
| Random-access p50/p99 | compbench     | all (esp. T.261 & Zarr) | Latency of `arr[t0:t1, :]` for random chunks — new; leverages T.261's block index  |
| Bitstream stability   | compbench     | T.261 esp.              | Re-encode round-trip determinism; regressions on codec upgrades                    |

### 4.6 Dataset ingestion

Start with three loaders, each behind one YAML schema:

1. **SpikeInterface path** — anything `si.read(...)` handles (SpikeGLX, OpenEphys, NWB, Zarr, MEArec).
2. **DANDI shortcut** — `dandi-cli` fetches a byte range or file subset; useful for CI and for evaluating what DANDI actually stores.
3. **Generic multichannel waveform** — EDF/BDF/MEF/HDF5 for ECG/EEG/EMG.

New datasets are added by dropping a YAML into `configs/datasets/`. No code changes.

---

## 5. Phased delivery

Ordered by increasing scope; each phase is independently useful and PR-sized.

### Phase 0 — Scaffold + CLI primitive (0.5–1 week)

- `pyproject.toml`, `tox.ini`, `pre-commit`, `.github/workflows/ci.yml`, `LICENSE` (MIT).
- Skeleton package layout per §4.
- **`compbench` CLI** (§4.1) with `encode`, `decode`, `eval`, `run`, `list-codecs`, `describe-codec` subcommands. Only `blosc-zstd` registered at this stage — proves the plumbing before we start wrapping harder codecs.
- **con-duct wired in** (§4.3): smoke test invokes `duct compbench run …` and the aggregator reads both `metrics.json` and the `duct-*.jsonl` to produce one joined row.
- Reproducibility smoke: `make smoke` generates 10 s of MEArec data → `duct compbench run --codec blosc-zstd` → passes CR + round-trip assertions → aggregated row has wall-time from con-duct. Runs in < 2 min on CI.

**Verify:** CI green; a single `duct compbench run …` invocation on a laptop produces both artifacts and the aggregator emits one Parquet row.

### Phase 1 — Reimplement paper's codec sweep, dataset-agnostic (1–2 weeks)

- Loaders for SpikeInterface + MEArec.
- Codecs registered via entry points: `blosc-{lz4,lz4hc,zlib,zstd}`, `gzip`, `lzma`, `zstd`, `flac`, `wavpack` (via existing `wavpack-numcodecs`).
- Snakemake DAG enumerates (dataset × codec × level × chunk × shuffle); each rule wraps one `duct compbench run …` cell in the `compbench-base` container (CPU-only) → writes `metrics.json` + `duct-*.jsonl` → aggregator joins to Parquet.
- Sorter-in-the-loop cells (lossy sweep) run in `compbench-ks25` per `configs/profiles/paper.yaml` — this matches the paper's Kilosort 2.5 exactly.
- Reproduce **Figure 2 & Figure 3** of the paper on at least one Buccino et al. dataset (IBL NP1 recording, plus one AIND NP1 for sanity) to validate the framework.

**Verify (revised 2026-08-19):** the paper's Fig 2 / Fig 7 report **distributions** over 8 NP1 recordings × up to 9 shuffle+level configs (N = 48-72 per codec). A single-recording × single-config point from our sweep is one point in that distribution and will not necessarily hit the paper's mean. The revised gate is:

1. **Ranking match:** our sweep reproduces the paper's codec ordering
   (lzma > zstd L22 > blosc-zstd L9 > blosc-zlib > gzip ≈ zlib > blosc-lz4hc >
   blosc-lz4 > lz4) on any single recording. **Necessary but not sufficient.**
2. **Median-of-8 match:** run our sweep on the same 8 NP1 recordings; take the
   per-codec median across recordings + configs; compare against the paper's
   published mean-of-8. Target: **within ± 5% of the paper's mean, or within
   the paper's reported SD** (whichever is looser). Both raw (matches Fig 2)
   and band-pass (matches Fig 7) should be reported side-by-side.
3. **con-duct sanity:** peak-RSS ranks codecs plausibly (`lzma` > `blosc-zstd` etc).

Paper's per-recording CSVs live in the Code Ocean capsule
`AllenNeuralDynamics/aind-capsule-ephys-compression-results` (data asset,
account required) — fetch them once, drop the per-recording numbers into
`.specify/specs/paper-cited-numbers.yaml`, and let the aggregator diff
automatically.

### Phase 2 — T.261 `numcodecs` wrapper (~6 engineer-days; no external blockers)

Reference software already at `src/bwc/` (tag `BWC-6.0`) with Linux build + lossless smoke-test verified (§2.3). Effort budget from the codebase review:

| Sub-task                                                          | Days |
| ----------------------------------------------------------------- | ---- |
| In-memory stream shim (`PacketWriteIf`/`ReadIf` over stringstream) | 1    |
| `pybind11` glue: `encode(int16 buf, cfg) → bytes`; `decode` inverse | 2    |
| `numcodecs.Codec` subclass + config dict ↔ key=value serialisation | 1    |
| Round-trip pytest suite + `cibuildwheel` CI                       | 2    |

Concrete steps:

- Convert `src/bwc/` from plain clone to git submodule pinned at `BWC-6.0` (or later tag if one lands before we start).
- Package `t261-numcodecs`: `pyproject.toml` with `scikit-build-core` backend; require `cmake>=3.15`, `pybind11`, `numpy`; ship `-DCMAKE_CXX_FLAGS="-Wno-restrict"` in the build config so GCC 12 wheels build.
- **Binding:** `pybind11` (not cffi — codebase is C++20 through-and-through, and pybind11 handles the numpy-int16 buffer protocol directly).
- **Threading contract:** hold a per-codec-instance `std::mutex` around each encode/decode call to serialise access to the `g_cfg` / `g_logStream` process-globals; document that a single `T261` codec instance is not thread-safe (Python GIL makes this a non-issue in normal use).
- Seed `configs/codecs/t261-*.yaml` from the 23 stock `.cfg` presets under `src/bwc/cfg/`.
- Produce a `manylinux_2_28_x86_64` wheel via `cibuildwheel`; publish to TestPyPI first, then PyPI.
- Register the `numcodecs` entry point → `compbench list-codecs` shows `t261` after install with no benchmark-side edits.
- Optional friendly upstream contribution: a ~50-line refactor exposing a flat `encode_buffer()` function in `EncLib`, plus the `-Wno-restrict` fix. Land after our own wrapper is working, not before.

**Verify:** `zarr.array(x, compressor=T261(preset="EEG_lossless"))[:] == x` on synthetic multichannel data; lossless CR reproduces the ~11× seen on the CLI smoke test; wheel installs cleanly via `pip install t261-numcodecs` on a fresh venv; `compbench list-codecs` shows `t261` post-install.

### Phase 3 — T.261 in the sweep + new metrics (1 week)

- Add T.261 to `configs/codecs/*.yaml` with a matrix of `level`, `lossless/lossy/near-lossless`, `bps` targets matching WavPack-Hybrid's range so plots are apples-to-apples.
- Implement PRD/PRDN, random-access latency.
- Run the full paper-comparable sweep on the exact IBL/AIND datasets Buccino et al. used → produce apples-to-apples plots (T.261 vs WavPack vs FLAC vs blosc-zstd on identical inputs).
- Deliver the first public report: "T.261 in the context of Buccino et al. 2023."

**Verify:** T.261 sits on or beats WavPack on lossless CR (its design claim); document any surprises. Reader can compare T.261 directly against the paper's figures without any dataset caveats.

### Phase 3.5 — Scale-out fixes (from 5-reviewer synthesis 2026-08-19)

Independent reviewer sweep flagged specific blockers between "1-recording
smoke works" and "16-recording paper reproduction works". Track here so
they don't get lost:

- **[R5-C1] Band-pass preprocessing OOMs at 1200 s.** `filtfilt` on 27 GB int16
  promotes to 110 GB float64 + internal buffers → ~200-250 GB peak per cell.
  Fix: chunk along channels (independent per channel per current docstring),
  or use `sosfiltfilt` on float32, or move to SpikeInterface's lazy
  `bandpass_filter` and materialize in chunks via `get_traces(start_frame=…)`.
- **[R5-C2] T.261 joint-channel EEG lossless unbounded.** >30 min at 10 s;
  extrapolates to 60+ h at 1200 s. Fix (any of): chunk by channel-group (8×
  48-channel subproblems), drop from `paper-real.yaml` until Phase 2b lands,
  or dedicate an 8 h `resources.time_min` slot per cell.
- **[R5-H1] Profile YAML doesn't scale to 16 × 3 datasets.** Currently one
  YAML per dataset variant; 48 hand-written YAMLs isn't workable. Fix:
  extend `expand_matrix` with `datasets_matrix:` block that cross-products
  `template × recording_id × preprocessing`.
- **[R5-H2] Memory-bound parallelism.** Runner holds original + encoded +
  decoded simultaneously during round-trip check. At 1200 s that's ~24 GB ×
  3 = 72 GB per cell. Fix: release input buffer before decode; add a
  `--skip-roundtrip` flag for the wide sweep.
- **[R4-H1] Preprocessing lives outside `datasets.load()`.** Only the YAML
  loader invokes it; direct `aind-benchmark:` URI-scheme use bypasses.
  Fix: move preprocessing invocation into `datasets.load()` OR make it a
  distinct pipeline stage (`compbench preprocess`).
- **[R4-M5] `LoadedDataset` not frozen; in-place mutation in yaml_loader.**
  Use `dataclasses.replace` for post-load transformations.
- **[R1-H3] No sorting-fidelity / waveform-features metrics.** Every
  "acceptable distortion" claim on lossy T.261 needs these before use.
  Kilosort agreement (against paper's Kilosort 2.5 baseline) + waveform
  peak-to-valley/FWHM/peak-to-trough (paper's Fig 5-6). Belongs in Phase 3
  metric expansion.
- **[R1-M4, R5-M4] Chunk-size sweep missing.** Paper Fig 2/7 averages across
  chunk sizes 0.1/1/10 s + shuffle variants. Add to profile matrix.

### Phase 4 — Dataset extension (scheduled after Phase 3 report ships)

Two directions, both optional relative to the primary Phase-3 goal:

- **Ephys extension:** Neuropixels v2 "quads" and other newer DANDI holdings — pick 2–3 recordings representative of the current data DANDI is ingesting.
- **Clinical extension:** EDF/BDF loader + 3–5 public ECG/EEG datasets (PhysioNet MIT-BIH, TUH EEG, etc.), covering T.261's clinical envelope. Coordinate dataset choice with WG-32 co-chairs at this point (deferred action #6/#7 in §10).

**Verify:** framework accepts new datasets via one YAML each, no Python edits; per-modality reports render from the same aggregator.

### Phase 5 — Polish + publish (1 week)

- Quarto report at `report/index.qmd` renders Parquet → HTML with interactive filters.
- Zenodo DOI on the results artifacts.
- Write a short methods note (blog post or preprint) inviting community contributions of datasets/codecs.

---

## 6. Decisions (locked 2026-08-18)

1. **Orchestrator: Snakemake.** ✓ Confirmed. Python-native, cleaner SLURM/K8s integration than raw scripts, no JVM dependency.
2. **Containers: reuse the AIND per-step image family from `ghcr.io/AllenNeuralDynamics/…`** (see [`aind-ephys-pipeline` architecture](https://aind-ephys-pipeline.readthedocs.io/en/latest/architecture.html)), pinned at tag `si-0.103.0` to match their published pipeline. Three derived images (§4 layout):
   - `compbench-base`  — CPU-only; FROM `aind-ephys-pipeline-base`; hosts `compbench` + `t261-numcodecs` + `wavpack-numcodecs` + `con-duct`. Used for all compression cells and the compression-only ×RT/CR sweep.
   - `compbench-ks25` — CPU-only; FROM `aind-ephys-spikesort-kilosort25`; adds `compbench`. Used for **paper-reproduction lossy runs** (KS2.5 was the paper's sorter).
   - `compbench-ks4`  — **CUDA-required**; FROM `aind-ephys-spikesort-kilosort4`; adds `compbench`. Used when the configured sorter is KS4 (default for new-dataset runs).
   The per-step split means the compression sweep never pays the GPU-image size/pull cost; only lossy-eval cells that actually sort do.
3. **Spike sorter: configurable per run; paper reproduction pins Kilosort 2.5.** `configs/profiles/paper.yaml` → sorter=`kilosort2_5`, image=`compbench-ks25`. `configs/profiles/full.yaml` (new-dataset runs) → sorter=`kilosort4`, image=`compbench-ks4`. `spykingcircus2` also registered but not on the default path.
4. **Wrapper hosting: `src/t261_numcodecs/` in this repo for now.** Rationale in §4.1a. If external consumers (DANDI ingest, pynwb, xarray) start depending on it, we split it into `dandi/t261-numcodecs` — the wrapper package layout is designed to make that move trivial (swap `../bwc/` path for `vendor/bwc/` submodule; no other changes).
5. **First public report uses Buccino et al.'s exact datasets** — the goal is to slot T.261 into the *same* comparison the paper made, so the reader sees T.261 alongside FLAC / WavPack / blosc-zstd on identical inputs. Expansion to new datasets — including Neuropixels v2 "quads" and other DANDI holdings — is explicitly a follow-up phase, not a Phase-3 blocker.

**Deferred (revisit when we have first results):**

- Emailing Buccino/Siegle (Allen) with attribution note.
- Emailing DICOM WG-32 co-chairs for preferred ECG/EEG datasets.

---

## 7. Risks and mitigations

| Risk                                                                              | Likelihood | Impact | Mitigation                                                                                                              |
| --------------------------------------------------------------------------------- | ---------- | ------ | ----------------------------------------------------------------------------------------------------------------------- |
| `vceg-sw/bwc` upstream ABI drift between tagged releases                          | med        | low    | Pin the submodule; wrap incompatible APIs behind `T261.protocol_version`; CI matrix over supported bwc tags.            |
| T.261 reference code is Windows-only or hard to build on Linux                    | **retired**| —      | Verified 2026-08-17: builds cleanly on Linux/GCC-12 with `-Wno-restrict`; lossless smoke test passed (§2.3).            |
| `g_cfg` / `g_logStream` process-globals cause thread races                        | high       | low    | Per-codec-instance mutex around each encode/decode; documented single-instance-not-thread-safe contract (§4.2, §2.3).  |
| GCC 12 `-Werror=restrict` false positive in `EDFReader.h`                         | high       | low    | One-flag workaround (`-Wno-restrict`) baked into wrapper's cmake args; disappears on GCC 13+. Consider upstream PR.    |
| No flat C API in ref-sw makes the binding harder than a `pyflac`-style wrapper    | high       | low    | In-memory `PacketWriteIf`/`ReadIf` shim (~200 LoC) avoids upstream patches; optional ~50-line upstream refactor later. |
| T.261 CR is not competitive with WavPack on 30 kHz ephys                          | med        | low    | Fine — negative results are still valuable; report honestly. May be more competitive on ECG/EEG.                        |
| DANDI/NWB/Zarr compatibility of T.261-compressed data blocks Zarr consumers       | high       | med    | Publish `t261-numcodecs` on PyPI so any consumer with the wheel can decode.                                             |
| Spike-sorter version drift changes "ground-truth" agreement across runs           | med        | med    | Pin sorter versions in container; report both KS2.5 (paper-comparable) and KS4 (current).                               |
| Cost / compute for full sweep (paper used 6 300 jobs on 16-CPU AWS)               | low        | med    | Start with a `paper` profile that hits ~10% of the sweep; `full` reserved for a milestone run.                          |
| Buccino et al. framework code has bit-rotted since 2023 (SpikeInterface API drift) | med        | low    | Reimplement, don't fork — we own the code, upstream stays untouched.                                                    |

---

## 8. Non-goals

- Not building a new codec.
- Not reimplementing Kilosort / SpikeInterface.
- Not producing a novel scientific claim about ephys compression — the goal is a *tool* and a *reference report*.
- Not making DANDI ingest immediately switch codecs — that is a separate downstream conversation informed by our report.

---

## 9. Success criteria

1. `git clone && make smoke` → passes on a laptop with Docker in < 5 min.
2. A user can run a single experiment with one command — no Snakemake, no Docker: `duct compbench run --input my.nwb --codec t261 --codec-params level=3,bps=2.25 --output-dir /tmp/x` produces `metrics.json` + `duct-*.jsonl`.
3. `make paper DATASET=configs/datasets/ibl-np1-sample.yaml` → reproduces Buccino et al. Fig 2/3 numbers within ± 5%.
4. `make full` → produces a Parquet table + HTML report comparing T.261 against every codec in the paper on ≥ 1 ephys and ≥ 1 clinical modality dataset, with cost columns (peak RSS, mean CPU %) sourced from con-duct alongside correctness columns from `compbench`.
5. A DICOM WG-32 member (or a DANDI dev) can add a new dataset via one YAML file and rerun without touching Python.
6. The `t261-numcodecs` wrapper is installable, tested, and used by at least one external consumer (candidate: `dandi-cli` or `pynwb`) as a validation of API cleanliness.

---

## 10. Immediate next actions (if this plan is approved)

1. ~~Verify a Linux build of `vceg-sw/bwc`.~~ **Done 2026-08-17** — see §2.3. Builds on GCC 12 with `-Wno-restrict`; lossless round-trip byte-exact at ~11× CR on synthetic EEG-like input.
2. **Deferred until first results.** Ask WG-32 co-chairs whether they have a preferred set of ECG/EEG datasets.
3. **Deferred until first results.** Confirm with the Allen Institute (Buccino, Siegle) that a reimplementation-with-attribution is welcome.
4. **Now: land Phase 0** (scaffold + `compbench` CLI + con-duct wiring + CI smoke) in this repo — self-contained, unblocks everything else.
5. (Nice-to-have, low priority) Watch for the T.261 specification PDF to appear at `https://www.itu.int/rec/T-REC-T.261` — as of 2026-08-18 it is not yet published. Not on the critical path; the reference software is our primary source.

---

## References

- Buccino, A. P. et al. *Compression strategies for large-scale electrophysiology data*, J. Neural Eng. 20, 056001 (2023). [DOI:10.1088/1741-2552/acf5a4](https://doi.org/10.1088/1741-2552/acf5a4)
- Paper code: <https://github.com/AllenNeuralDynamics/ephys-compression>
- WavPack numcodecs wrapper: <https://github.com/AllenNeuralDynamics/wavpack-numcodecs>
- Nextflow pipeline template: <https://github.com/AllenNeuralDynamics/aind-ephys-hybrid-benchmark>
- DICOM WG-32: <https://www.dicomstandard.org/activity/wgs/wg-32>
- DICOM Sup 253 (waveform compression transfer syntaxes): <https://www.dicomstandard.org/news-dir/current/docs/sups/sup253.pdf>
- ITU-T T.261 / H.BWC work item: <https://www.itu.int/ITU-T/workprog/wp_item.aspx?isn=21060>
- ITU-T H.BWC Call for Proposals: <https://www.itu.int/en/ITU-T/studygroups/2022-2024/16/Documents/docs/CfP-H.BWC-TD-PLEN-0286-R1-Clean.pdf>
- ISO/IEC 23003-8: <https://www.iso.org/standard/92515.html>
- ITU-T account registration: <https://www.itu.int/en/ITU-T/focusgroups/mv/Pages/reg.aspx>
- **T.261 / H.BWC reference software (Clear BSD, public):** <https://vcgit.hhi.fraunhofer.de/vceg-sw/bwc>
- con/duct execution profiler: <https://github.com/con/duct> (`pip install con-duct`)
