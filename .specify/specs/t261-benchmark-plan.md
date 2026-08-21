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

**Metrics:** compression ratio (CR); compression speed and decompression speed as `×RT` (multiples of real-time on a 16-CPU AWS EC2 node); RMSE after 300–6000 Hz band-pass filter; spike-sorting accuracy/precision/recall with Kilosort 2.5 (ground-truth on simulated data, agreement-based curation on experimental); waveform-feature errors (peak-to-valley, half_width — the SI metric name; the paper's prose says half_width but its code computes half_width — and peak-to-trough).

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

Correctness metrics live in `compbench` (`metrics.json`). Cost/throughput metrics come from con-duct (`duct-*.jsonl`) and are joined at report-aggregation time. Sorting-fidelity metrics live in `compbench.metrics.sorting`; the sorting-eval pipeline (§4.7) writes them into per-cell `sorting.json`.

| Metric                        | Source                        | Applies to              | Notes                                                                                    |
| ----------------------------- | ----------------------------- | ----------------------- | ---------------------------------------------------------------------------------------- |
| CR                            | compbench                     | all                     | bytes_original / bytes_compressed                                                        |
| Encode / decode ×RT           | con-duct + manifest           | all                     | `recording_duration / duct.wall_time`; comparable across native-threaded codecs         |
| Peak RSS, mean CPU %          | con-duct                      | all                     | resource envelope; catches native-code hotspots                                          |
| RMSE (full-band)              | compbench                     | lossy                   | in signal units                                                                          |
| RMSE (band-limited)           | compbench                     | ephys lossy             | 300 – 6 000 Hz on the reconstruction ERROR — paper Fig 4-6 methodology (verified 08-20)  |
| PRD, PRDN                     | compbench                     | ECG lossy               | standard clinical distortion metrics; required for T.261 ECG conformance                 |
| signal_std, rmse/std %        | compbench                     | lossy                   | interpret RMSE in signal units; pooled + per-channel-median                              |
| **Sorting accuracy / precision / recall** | compbench.metrics.sorting | **simulated ephys lossy** | **Paper Fig 10** — per-GT-unit distributions; requires MEArec ground-truth loader        |
| **Unit classification counts**| compbench.metrics.sorting     | **ephys lossy**         | **Paper Fig 11-12** — well_detected / false_positive / redundant / overmerged           |
| **Spike-train agreement**     | compbench.metrics.sorting     | **experimental ephys**  | **Paper Fig 13** — spike-time overlap fraction vs lossless baseline; excess-spike symmetry |
| **Waveform-feature errors**   | compbench.metrics.sorting     | **ephys lossy**         | **Paper Fig 14** — peak-to-valley, half_width, peak-to-trough on main + peripheral (60 µm) channels |
| **QC pass fraction**          | compbench.metrics.sorting     | **experimental ephys**  | Siegle 2021 curation (ISI-viol-ratio < 0.5, presence > 0.95, amp cutoff < 0.1); Fig 12 summary   |
| Random-access p50/p99         | compbench                     | all (esp. T.261 & Zarr) | Latency of `arr[t0:t1, :]` for random chunks — new; leverages T.261's block index        |
| Bitstream stability           | compbench                     | T.261 esp.              | Re-encode round-trip determinism; regressions on codec upgrades                          |

### 4.6a Spike-sorting fidelity pipeline (paper §3.2.2, §4.2)

The core scientific question is not "what's the compression ratio?" — the paper's headline claim is "**WavPack Hybrid at 2.25 bps preserves spike waveforms and does not affect sorting accuracy**." Our T.261 lossy Pareto is only interesting if we can make (or disprove) the analogous claim. This subsection specifies the sorting-fidelity pipeline that produces the paper's Fig 10-14 numbers on our reconstructed traces.

**Pipeline stages** (Snakemake rules; each stage is a separate `compbench` subcommand for individual invocation):

1. **`compbench run` (existing)** — encode + decode + full-band + band-limited RMSE + PRDN. Produces `reconstructed.npy` per cell when `--keep-reconstructed`.
2. **`compbench sort --input reconstructed.npy --sorter kilosort2_5`** *(NEW, Phase 3.5)* — sort the reconstructed traces. Uses `spikeinterface.sorters.run_sorter(sorter_name=..., recording=...)` inside the `compbench-ks25` container (Kilosort 2.5 to match paper). Produces `sorting.pkl` / `sorting.zarr`.
3. **`compbench compare-sorting`** *(NEW, Phase 3.5)* — two modes:
    - **`--against-ground-truth mearec.h5`** — GT comparison (simulated data). Uses `spikeinterface.comparison.GroundTruthComparison`. Emits per-cell `sorting.json` with per-unit accuracy/precision/recall + unit-count classifications.
    - **`--against-baseline lossless-cell-dir`** — pairwise comparison (experimental data). Uses `compare_multiple_sorters (match_score=0.9)`. Emits per-unit spike-time agreement + excess-spike symmetry + QC pass-fraction.
4. **`compbench sort-waveforms`** *(NEW, Phase 3.5)* — build `SortingAnalyzer` on baseline + candidate reconstructions, compute peak-to-valley / half_width / peak-to-trough on main + 60 µm peripheral channels (paper Fig 14).
5. **Aggregator** flattens the new `sorting.json` files into `report.parquet` alongside the compression metrics.

**Reference codec baselines** in every sorting-eval profile (paper §3.2):

- **Bit truncation** — the paper's simple baseline. Composed as `blosc-zstd` with `numcodecs.FixedScaleOffset(scale=1/2**n)` as the pre-filter. Register ONE `bittrunc` codec taking a `bits` param (0..7) — not eight registry keys; `wavpack` takes `bps` as a param, not `wavpack-2.25` in `compbench.codecs`.
- **WavPack Hybrid** — the paper's headline lossy result (`wavpack` with `bps ∈ {6, 5, 4, 3.5, 3, 2.5, 2.25}`). Already registered; profile-driven sweep.
- **T.261** — our target codec; QP sweep + preset variants.

**Expected sweep dimensions** (paper §3.2 Fig 10 baseline for NP1):
- ~7 QP points × 2 T.261 presets + 7 WavPack-Hybrid bps + 8 bit-truncation levels = ~29 lossy codec configs
- Plus 1 lossless baseline per codec family
- × MEArec-simulated NP1 + NP2 (2 recordings; 100 s slice → ~30 min encode + ~30 min sort per cell)
- Total: ~60 cells; 30-60 hours wall on 8 CPU + 1 GPU. Fits an overnight run on a modest workstation.

**Container:** `compbench-ks25` (already recipe-defined; needs Kilosort 2.5 to match paper). GPU required for either sorter — Kilosort 2.5 is MATLAB + CUDA MEX, not CPU-only (corrected 2026-08-20). `compbench-base` handles the encode/decode stage.

**Verification target** (Phase 3 close-out):
- (a) A **two-run lossless null control** is required, and is not expected to be
  perfect. Kilosort is not deterministic — see the expanded note in Phase 3b
  and `metrics.sorting.run_to_run_floor`. An earlier revision of this line
  claimed lossless sorting is "deterministic given same sorter seed", which is
  the opposite of the paper's finding.
- (b) T.261 QP=1.5 judged against the endpoints that move — `num_false_positive`,
  `num_well_detected`, the ordered-agreement curve vs the measured two-run
  lossless floor, and the 10 % waveform-feature line. (The "within 5 %"
  criterion previously here was invented and has no power — see §5 Phase 3b.)
- (c) T.261 QP=X where X is the "sorting-transparent" boundary — the highest QP that stays within the paper's stated ~10 % waveform-feature error tolerance.
- (d) Failure modes documented (which units are affected at higher QP; symmetric or biased?).

### 4.6b Matching the paper's measurement conditions (added 2026-08-20)

Reading the analysis capsule
([`aind-capsule-ephys-compression-results`](https://github.com/AllenNeuralDynamics/aind-capsule-ephys-compression-results),
`code/lossless.ipynb`) alongside the published Methods turned up three
conditions our sweep did not reproduce. Each one moves CR, so a
comparison against the paper is not meaningful until they match.

**(a) LSB correction — `lsb != 'false'` in the capsule's headline query.**

SpikeGLX writes raw ADC values, giving a least-significant bit of 1.
Open Ephys rescales to a fixed 0.195 µV/sample regardless of hardware
gain, which for raw Neuropixels data makes the LSB **12 for NP1 and 3
for NP2** — i.e. every sample is a multiple of 12 (or 3), wasting
log2(12) ≈ 3.6 bits of entropy per sample on codecs that cannot see the
structure. Paper's Methods, verbatim:

> Prior to compression, we rescaled the Open Ephys data to have an LSB of
> 1 by first removing each channel's median (since scaling could
> introduce rounding errors) and dividing by either 12 or 3.

Per-session LSB values are in the paper's table 1:

| Source   | Probe | Acquisition | Gain (µV/sample) | LSB |
| -------- | ----- | ----------- | ---------------: | --: |
| IBL      | NP1   | SpikeGLX    | 2.34             |  1  |
| AIND     | NP1   | Open Ephys  | 0.195            | 12  |
| AIND     | NP2   | Open Ephys  | 0.195            |  3  |
| MEArec   | NP1/NP2 | simulated | 0.195            | 12 / 3 |

So 4 of the 8 NP1 recordings in our gate need it, and all 8 NP2. IBL
recordings are unaffected (LSB 1 -> `correct_lsb` applies NO operation at all;
median removal).

**This is an added axis, not a retrofit** — see §6 decision 6. Both
corrected and uncorrected AIND numbers are swept and reported.

**Verified on the real recordings (2026-08-20), 2 s slices, blosc-zstd
L9/bit, whole-buffer:**

| Recording      | modal sample step | paper LSB | CR raw | CR corrected | gain  |
| -------------- | ----------------: | --------: | -----: | -----------: | ----: |
| ibl-CSHZAD026  |                 1 |         1 |  2.558 |  *(no such condition)* | — |
| aind-625749    |                12 |        12 |  2.110 |        3.170 | 1.50x |
| aind-634571    |                12 |        12 |  2.071 |        3.112 | 1.50x |

**RETRACTED 2026-08-20:** an earlier version of this table gave
ibl-CSHZAD026 a "CR corrected 3.111 / gain 1.22x". That number was produced
by the bug fixed in `7106d9b` — `lsb_correction` removing the per-channel
median even at lsb=1. There is no "corrected" condition for a SpikeGLX
recording: `correct_lsb` is a documented no-op at lsb=1 and the paper marks
ibl-np1 `{"none": False}`. The row is kept, struck, rather than deleted,
because it was published.

Three things worth recording:

1. The paper's table-1 LSB values are directly observable in the data —
   AIND samples really do sit on a 12-count grid.
2. **The effect is ~50% on AIND recordings**, not a rounding-level
   detail. Half the NP1 gate set is AIND, so an uncorrected comparison
   against the paper would have been meaningless. Corroborated on the
   paper's own data: the AIND NP1 LSB-on/off CR ratio has median **1.452**
   (range 0.977-1.794, n=96).
3. *(Retracted — the "corrected CRs converge across sources" argument that
   stood here rested on the withdrawn IBL row above.)*

Note when measuring the grid empirically: use the **modal** difference
between adjacent distinct codes, not a gcd. A handful of samples per
channel sit one count off the grid — the very rounding artefacts the
paper's median-removal step exists to absorb — and a single off-grid
value collapses a gcd to 1.

**(b) Chunk duration — `chunk_duration == '1s'` in the headline query.**

The paper compresses through a Zarr store with chunks of (chunk_samples,
n_channels), sweeping 0.1 / 1 / 10 s, and every headline figure filters
to **1 s**. We were compressing the entire loaded buffer as a single
chunk, which is a different — and generally more favourable — condition,
since a codec sees far more context. Chunk duration becomes a profile
axis; CR is `original_bytes / sum(len(encoded_chunk))`.

This also makes the random-access latency metric (§4.5) meaningful, and
it is closer to how compressed ephys is actually stored.

**(c) Shuffle variants.** The paper's best configurations are
`blosc-zstd` at high level with **bit** shuffling, and `LZMA` with **no**
shuffling for NP1 / byte for NP2. Our profiles swept only `byte`, so we
were not measuring the paper's best general-purpose configuration at all.
All three shuffle options are now swept for the blosc family.

**Gate numbers now available without the Code Ocean data asset.** The
paper's Results text quotes medians ± SD with N = 8 per distribution;
they are transcribed into `.specify/specs/paper-cited-numbers.yaml`. The
capsule's per-recording CSVs would add distribution-level comparison but
are not required for the §5 gate. Note also that the paper reports
**median ± SD, not mean** (capsule cells 26/55/65/79 are
`.median().round(2)` / `.std().round(2)`) — earlier drafts of §5 said
"mean-of-8", which was wrong; our median-of-8 is directly comparable.

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

1. **Ranking match:** our sweep reproduces the paper's codec ordering.
   **Necessary but not sufficient.** Corrected 2026-08-20 — the ordering
   previously stated here had two inversions and was in fact our own
   byte-shuffle-only result mislabelled as the paper's. Derived from
   `benchmark-lossless.csv` under the capsule's headline filter:

   - NP1: `lzma > blosc-zstd > zstd > gzip ≈ zlib > blosc-zlib >
     blosc-lz4hc > blosc-lz4 > lz4`
   - NP2: `lzma > blosc-zstd > zstd > blosc-lz4hc > gzip ≈ zlib >
     blosc-zlib > blosc-lz4 > lz4`

   The paper says it in prose too (§3.1.4): *"LZMA produces the highest
   average CR, immediately followed by zstd, whose blosc implementation
   (blosc-zstd) appears to outperform the numcodecs version (zstd)."*
   Ordering is condition-dependent; compare only against
   `paper-reference-lossless.csv` rows at matching conditions.
2. **Paired per-recording match** (revised 2026-08-20; the previous
   median-vs-median ±5% criterion was ill-posed — see below). We run *the
   same 8 recordings* the paper ran, so the comparison is **paired** and
   between-recording variance is nuisance, not signal.

   For each (recording × codec × exactly-matched config) compute the ratio
   `ours / theirs` against the paper's **per-session** rows in
   `src/capsule-ephys-compression-results/data/ephys-compression-results/`
   `results-lossless/benchmark-lossless.csv`. (Not
   `paper-reference-lossless.csv` — that table is aggregated over sessions
   and has no `session` column, so a paired comparison cannot be computed
   from it.) Gate:

   - **median |ratio − 1| ≤ 2%**, and
   - **max |ratio − 1| ≤ 5%**, reported per recording so one bad recording
     is visible rather than averaged away.

   Both raw (Fig 2/6) and band-pass (Fig 7) reported side by side. Valid
   only against cells at the paper's conditions — LSB-corrected, 1 s
   chunks, matching level *and shuffle* (§4.6b).

   **Why the old criterion failed, three ways.** (a) *Aggregation
   mismatch*: it said "median across recordings **+ configs**", but every
   reference number is single-config. Pooling our configs biases us 10-17%
   against the stated target — 2-3× the tolerance — so the gate could fail
   a perfect reproduction. (b) *The ±5% clause was inert*: per-codec
   SD/median across the 8 NP1 recordings is 7.0-13.9%, so "±5% **or**
   within SD, whichever is looser" always degenerated to ±1 SD. (c) *It
   discarded the pairing*: measured, our paired agreement on CSHZAD026 is
   **0.2% median, 1.5% max across 11 codecs** at matched conditions (see
   `.specify/specs/results-2026-08-20-paired-reproduction.md`, the citable
   record) — the old +/-1SD gate was roughly 40-70x looser than that.

   (An earlier revision cited "0.06% median, 2.5% max" here. It conflated
   that run's codec count with deltas computed against the committed
   whole-buffer derivative at the paper's 1 s-chunk rows — a
   mismatched-conditions comparison, which is exactly the error this gate
   exists to prevent. Withdrawn.)
   looser than our actual reproducibility, and would have passed a run
   that was wrong by an order of magnitude.

   Report the pooled median-of-8 as a **descriptive** summary only, never
   as the gate; and when doing so, compare against the paper's *pooled*
   Fig-2 medians (NP1 lzma 2.52±0.31, blosc-zstd 2.38±0.36; NP2 1.85,
   1.76), never against its single-config Fig-6 numbers.

   Note the design is **unbalanced and partly confounded**: IBL recordings
   have 2 preprocessing conditions and AIND 4 (LSB correction is a no-op on
   SpikeGLX), so a "median-of-8" over an `lsb` cell is really a median over
   4 AIND recordings, and `lsb` is fully confounded with `source`. Report
   LSB effects per-source, never as a main effect.
3. **con-duct sanity:** peak-RSS ranks codecs plausibly (`lzma` > `blosc-zstd` etc).

The paper's own Results text quotes the medians ± SD we need; they are
transcribed into `.specify/specs/paper-cited-numbers.yaml` (2026-08-20).
The per-recording CSVs behind the figures are a Code Ocean *data asset*
(`ephys-compression-results`) — the analysis capsule
`AllenNeuralDynamics/aind-capsule-ephys-compression-results` is public on
GitHub but ships notebooks with outputs stripped. Those CSVs would enable
a distribution-level comparison (do our 8 points overlap theirs?); they
are not required for the median gate.

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

### Phase 3 — T.261 in the sweep + new metrics + sorting fidelity (2 weeks)

**3a. Codec + preprocessing sweep** (largely landed 08-20)
- Add T.261 to `configs/codecs/*.yaml` with a matrix of `level`, `lossless/lossy/near-lossless`, QP targets matching WavPack-Hybrid's bps range so plots are apples-to-apples. ✓
- Implement band-limited RMSE (paper Fig 4-6), PRD/PRDN. ✓
- Run the paper-comparable sweep on IBL/AIND datasets + MEArec-simulated. Partial (CSHZAD026 done; 15 more recordings pending on beefier host).

**3b. Sorting-fidelity pipeline** (the CORE scientific question — see §4.6a)
- Add MEArec loader (`compbench.datasets.mearec`). ✓ (skeleton)
- Implement `compbench.metrics.sorting.{gt_comparison_metrics, sorting_agreement, unit_classification, qc_pass_fraction, waveform_feature_errors}`. Skeleton landed; implementations reference `spikeinterface.comparison.{GroundTruthComparison, compare_multiple_sorters (match_score=0.9)}` + `spikeinterface.qualitymetrics.compute_quality_metrics`. Full impl deferred to Phase 3.5 [R1-H3].
- Add `compbench sort` / `compbench compare-sorting` / `compbench sort-waveforms` CLI subcommands.
- Register `bittrunc-N` (numcodecs.FixedScaleOffset+blosc-zstd) as the paper's other lossy baseline.
- Run `sorting-eval.yaml` profile on MEArec NP1 (100 s slice first, then full 600 s) + WavPack-Hybrid bps sweep + T.261 QP sweep + bit-truncation. Produce paper Fig 10-14 analogues.
- Deliver the first public report: "T.261 in the context of Buccino et al. 2023 — compression, distortion, AND sorting fidelity."

**Verify:**
- **Compression**: T.261 sits on or beats WavPack on lossless CR (its design claim).
- **Sorting fidelity (simulated).** The "within 5 % of accuracy/precision/
  recall" criterion previously stated here was **invented** — the paper
  states no such tolerance.

  What the vendored reference data actually shows is more interesting than
  the argument first written here. At NP1 bit-truncation 5, accuracy does
  drop 0.9981 -> 0.9268 (-7.1 %), so a 5 % accuracy gate would *fail* it —
  the paper's own prose ("only slightly affected") is contradicted by its
  own released numbers. But the failure is far more visible in the unit
  counts: false positives go **52 -> 1435** while `num_well_detected` only
  drops 100 -> 90. And the gate is still the wrong instrument: at
  bit-truncation *4* (CR 29.9, RMSE 4.70) accuracy holds at 0.9979 and a
  5 % gate passes, yet false positives are already rising. A scalar
  accuracy summary is a lagging indicator of a failure the unit counts
  show first.

  Use the endpoints that actually move: `num_false_positive` and
  `num_well_detected` (Fig 11); the ordered spike-train agreement curve
  against the **measured** two-run lossless floor (Fig 13), not a scalar
  summary of it; and waveform-feature relative error against the paper's
  only stated numeric tolerance, the **10 %** line drawn in Fig 14.
- **Sorting fidelity (experimental)**: T.261 QP=1.5 spike-train agreement > 0.95 vs lossless baseline; excess-spike distribution symmetric around 0.
- **Where T.261 breaks down**: document the QP boundary beyond which sorting fidelity degrades unacceptably; separate cell-per-cell "safe" vs "aggressive" bands.

Reader can compare T.261 directly against paper Fig 10-14 without dataset caveats.

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
- **[R1-H3 — PROMOTED to Phase 3b core, not deferred]** No sorting-fidelity /
  waveform-features metrics. Every "acceptable distortion" claim on lossy
  T.261 needs these before use. Skeleton landed 08-20: `compbench.metrics.sorting`
  + MEArec loader + `configs/profiles/sorting-eval.yaml` + `configs/datasets/mearec-*.yaml`.
  Implementations pending — requires (a) `spikeinterface.comparison` wiring,
  (b) new `compbench sort` / `compbench compare-sorting` CLI subcommands,
  (c) `compbench-ks25` container image built + tested with Kilosort 2.5.
  See §4.6a for the full pipeline spec (paper §3.2.2, §4.2).
- **[R1-M4, R5-M4] Chunk-size sweep missing.** Paper Fig 2/7 averages across
  chunk sizes 0.1/1/10 s + shuffle variants. Add to profile matrix.

### Phase 3.5 additions from round-2 review (2026-08-20)

- **[R1-H2] Per-channel PRDN.** Current `signal_std` is pooled across all 384
  channels → PRDN is pooled → underestimates typical per-channel distortion
  by ~1.8× on this recording. Add `prdn_per_channel_median_percent`, plus
  IQR + max, to metrics. Report the per-channel-median as the "reader-facing"
  number in headline tables.
- **[R2-H2] Sourcedata annex-key in manifest.** `input.provenance.params.path`
  is currently a filesystem string. Add `datasets/aind_benchmark.py` step that
  calls `git-annex lookupkey` on the recording file + records the containing
  subdataset commit SHA. Two runs against the same recording at different
  git-annex keys are then distinguishable from `manifest.json` alone.
- **[R2-H3] Surface preprocessing in report.parquet.** Aggregator flattens
  `input.provenance.preprocessing` into a `preprocessing_summary` column so
  a stranger reading the parquet can tell raw from band-pass without
  cross-referencing manifests.
- **[R4-M3, R5-H1] SHA-256 cache per input file.** `array_digest` is O(N)
  and runs once per cell → N codec cells × the same input hashed N times.
  Cache in `run_cell` (or `LoadedDataset.sha256_hex` cached property) to
  cut ~30 s per 27 GB cell.
- **[R2-H1] Backfill published pre-round-2 derivatives.** The two 2026-08-19
  derivatives (`compbench-2026-08-19-CSHZAD026-slice10s` and its `-bandpass`
  sibling) predate the PRDN/BWC-provenance additions and their `metrics.json`
  files lack the new columns. Either re-run those sweeps (the v2 landed
  2026-08-20 handles the bandpass case) or write a `backfill_manifest.py`
  that fills in what can be reconstructed.
- **[R3-fact-drift alarm] Numeric drift between docs and parquets.**
  Whenever `runner.py` grows a new metric field, existing docs cite it from
  memory. Add `compbench render-report --check-doc <RESULTS.md>` that
  asserts every quoted number in the doc matches the parquet within 0.01.
- **[R4-M4] `-sourcedata` YAML duplication.** Two `-{,-sourcedata}` variants
  per dataset scale badly at 16 recordings × 3 preprocessing. Consider a
  `path_base:` field or `${SOURCEDATA}` env-var interpolation in the loader
  so one YAML expresses both scratch and study-relative paths.

### Phase 4 — Dataset extension (scheduled after Phase 3 report ships)

Two directions, both optional relative to the primary Phase-3 goal:

- **Ephys extension:** Neuropixels v2 "quads" and other newer DANDI holdings — pick 2–3 recordings representative of the current data DANDI is ingesting.
- **Clinical extension:** EDF/BDF loader + 3–5 public ECG/EEG datasets (PhysioNet MIT-BIH, TUH EEG, etc.), covering T.261's clinical envelope. Coordinate dataset choice with WG-32 co-chairs at this point (deferred action #6/#7 in §10).

**Verify:** framework accepts new datasets via one YAML each, no Python edits; per-modality reports render from the same aggregator.

### Phase 4.5 — A container per codec, for reproducible setups (TODO)

**Motivation, learned the hard way.** Every codec in this benchmark has turned
out to have a host dependency that is invisible until it bites, and each one
was diagnosed only after it had already produced or blocked a number:

| Codec  | Host dependency | How it surfaced |
| ------ | --------------- | --------------- |
| wavpack | `wavpack-numcodecs` links a *system* libwavpack when `wavpack` is on PATH, else demands glibc exactly 2.35 or 2.39 | Unavailable across three hosts (2.36, 2.41) *and* inside AIND's own base image (2.31). The container advice we had written down was wrong. |
| t261   | BWC compiled from source; needs cmake + a C++20 compiler | Survived a base-image swap only because prebuilt binaries happened to persist |
| blosc  | Nondeterministic above one thread — same input, different bytes | Only found by hashing output across thread counts |
| flac   | `flac-numcodecs` has no PyPI release we can pin | Registers only if importable; silently absent otherwise |
| all    | glibc / Python ABI | A GPU attachment swapped Debian 12→13, glibc 2.36→2.41, Python 3.11→3.13 and killed the venv outright |

Chasing these per-host does not scale and does not reproduce. **Ship a
container per codec family**, each pinning its own userspace:

- `compbench-codec-audio` — wavpack + flac, on a glibc the upstream wheels
  actually target; the one image where the audio codecs are known-good.
- `compbench-codec-t261` — BWC built at a pinned tag, binaries baked in, so
  `t261` never depends on the host toolchain.
- `compbench-codec-general` — blosc / zstd / lzma / gzip / zlib, pinned
  `numcodecs` (remembering that 0.16 broke zarr 2.x).
- `compbench-sorting` — CUDA + Kilosort, the only image needing a GPU.

Requirements:

1. **A cell records which image produced it.** `manifest.json` gains an
   `image` block (registry digest, not tag) so a number is traceable to a
   userspace, the way it already is to a git SHA and a BWC SHA.
2. **Digest-pinned, not tag-pinned.** `si-0.103.0` is mutable; a digest is not.
3. **Reproducible across runtimes.** Must work under apptainer sandboxes as
   well as SIFs — `/dev/fuse` is absent on at least one host here, so SIF
   mounting fails while `--sandbox` works.
4. **Publish them.** A reader reproducing our tables should pull an image, not
   rebuild a toolchain.
5. **Verify, don't assume.** Every claim of the form "codec X works in image Y"
   in this repo has to be tested, because the one we inherited was false.

Until this lands, host-native setup is documented in `.env`,
`scripts/build_wavpack.sh` and DEPLOY §1c — and it is exactly the fragility
this phase exists to remove.

### Phase 5 — Polish + publish (1 week)

- Quarto report at `report/index.qmd` renders Parquet → HTML with interactive filters.
- Zenodo DOI on the results artifacts.
- Write a short methods note (blog post or preprint) inviting community contributions of datasets/codecs.

---

## 6. Decisions (locked 2026-08-18)

1. **Orchestrator: Snakemake.** ✓ Confirmed. Python-native, cleaner SLURM/K8s integration than raw scripts, no JVM dependency.
2. **Containers: reuse the AIND per-step image family from `ghcr.io/AllenNeuralDynamics/…`** (see [`aind-ephys-pipeline` architecture](https://aind-ephys-pipeline.readthedocs.io/en/latest/architecture.html)), pinned at tag `si-0.103.0` to match their published pipeline. Three derived images (§4 layout):
   - `compbench-base`  — CPU-only; FROM `aind-ephys-pipeline-base`; hosts `compbench` + `t261-numcodecs` + `con-duct`. **Note (2026-08-20): this image cannot supply WavPack** — it is glibc 2.31 and `wavpack-numcodecs` needs 2.35/2.39; WavPack is handled natively (see §Phase 4.5 and `scripts/build_wavpack.sh`). Never built or run to date.
   - `compbench-ks25` — **CUDA required** (KS2.5 is MATLAB + CUDA MEX, not CPU-only); FROM `aind-ephys-spikesort-kilosort25`; adds `compbench`. Used for **paper-reproduction lossy runs** (KS2.5 was the paper's sorter).
   - `compbench-ks4`  — **CUDA-required**; FROM `aind-ephys-spikesort-kilosort4`; adds `compbench`. Used when the configured sorter is KS4 (default for new-dataset runs).
   The per-step split means the compression sweep never pays the GPU-image size/pull cost; only lossy-eval cells that actually sort do.
3. **Spike sorter: configurable per run; paper reproduction pins Kilosort 2.5.** `configs/profiles/paper.yaml` → sorter=`kilosort2_5`, image=`compbench-ks25`. `configs/profiles/full.yaml` (new-dataset runs) → sorter=`kilosort4`, image=`compbench-ks4`. `spykingcircus2` also registered but not on the default path.
4. **Wrapper hosting: `src/t261_numcodecs/` in this repo for now.** Rationale in §4.1a. If external consumers (DANDI ingest, pynwb, xarray) start depending on it, we split it into `dandi/t261-numcodecs` — the wrapper package layout is designed to make that move trivial (swap `../bwc/` path for `vendor/bwc/` submodule; no other changes).
5. **First public report uses Buccino et al.'s exact datasets** — the goal is to slot T.261 into the *same* comparison the paper made, so the reader sees T.261 alongside FLAC / WavPack / blosc-zstd on identical inputs. Expansion to new datasets — including Neuropixels v2 "quads" and other DANDI holdings — is explicitly a follow-up phase, not a Phase-3 blocker.

6. **Published derivatives are IMMUTABLE. Never discard, overwrite, or
   re-run-in-place a result that has been committed to the study.**
   (Locked 2026-08-20.)

   Every sweep already committed under
   `results/dandi-t261-compression-study/derivatives/` is a permanent
   record of what this code produced against that input on that date. In
   particular the **original AIND numbers — measured on the data exactly
   as the AIND benchmark bucket ships it — are an absolute. They are not
   corrected, superseded, or replaced.**

   This matters right now because the paper applies an *LSB correction*
   to Open Ephys data before compressing (§4.6b): it removes each
   channel's median and divides by 12 (AIND NP1) or 3 (AIND NP2). That
   correction changes CR substantially. It would be easy to treat the
   uncorrected AIND numbers as "wrong" and re-run over them. They are
   not wrong — they are the compression performance of the data as
   distributed, which is a legitimate and separately interesting result
   (it is what a naive downstream consumer of that bucket would actually
   get).

   Therefore:

   - LSB correction is a **new axis**, never a fix. Both `lsb_correction:
     off` and `lsb_correction: on` are swept and both are reported, with
     the axis surfaced in `report.parquet` and in the rendered table.
   - The same rule governs every other methodology change that moves a
     number — chunk duration, shuffle variant, filter representation.
     Add a condition; do not silently redefine an old one.
   - A new sweep goes in a **new dated derivative directory**.
   - **Measurements are immutable; narrative is correctable.** Refined
     2026-08-20: `metrics.json`, `manifest.json` and `report.parquet` in a
     committed derivative are never modified — verified, `git log
     --diff-filter=M` over those paths is empty. A derivative's
     `RESULTS.md` *may* be corrected in place when it states something
     false, because leaving a known-wrong claim standing is worse than
     editing it; the correction must be visible in git history and say
     what it corrects. (The original wording said "existing ones are never
     edited", which the repo's own history already contradicted at
     `a897d39` and `f7b497e`.)
   - If an old derivative lacks a column a new metric added, that is a
     fact about when it was run, and the aggregator tolerates it ([R2-H1]).
   - Corollary already applied: `preprocessing._bandpass` deliberately
     stays on `filtfilt` rather than moving to the numerically nicer
     `sosfiltfilt`, because the switch would shift every published
     band-pass CR. If we adopt SOS it will be as a labelled condition
     with a before/after, not as a quiet improvement.

7. **Reproduction cells MUST match the paper's operations exactly. Where
   the paper used a library, call that library.** (Locked 2026-08-20.)

   Every methodology defect this project has hit came from an operation
   that *resembled* the paper's rather than *being* it — an order-4 `ba`
   filter for their order-5 SOS, a whole-buffer filter for their chunked
   one, a time delta for their flattened one, `lsb=1` meaning
   median-removal instead of nothing, a 60 s slice for their full
   recording. Each produced numbers that looked plausible and were not
   comparable, and each was found only by accident.

   The rule, in force for any cell intended to reproduce a published
   figure:

   - **No convenience slicing.** Use the recording the paper used, at its
     full length. A slice is a different measurement: on band-passed data
     a 60 s slice costs blosc-zstd **1.9 %** against the full recording,
     which alone would consume most of the §5 gate budget.
   - **Filtering, chunking, scaling and curation follow the paper's own
     code**, not its prose — the two disagree in at least five places we
     have found (§4.6b, and the `bandpass_300-15000` label that is really
     500-14999 Hz).
   - **Prefer delegation to reimplementation.** `preprocessing._bandpass`
     now calls `spikeinterface.preprocessing.bandpass_filter` and
     materialises it in the paper's chunks; verified **bit-identical** to
     a real SpikeInterface `.save()` pipeline over 20 s x 384 channels.
     Reimplementing it "carefully" is how we got an order-4 filter that
     was wrong by up to 10 counts per sample and right to within 0.2 % on
     CR — invisible to the metric we were checking.
   - **A faster, non-matching variant may exist, but must be labelled and
     may not back a reproduction claim.** `legacy-o4-ba` is retained only
     so the three committed derivatives stay interpretable.
   - **Anything that cannot be matched is recorded as a known deviation**
     with its measured size, next to the number it affects — not left
     implicit. Current list: FLAC `channel_chunk_size=2` (we chunk only
     along time), WavPack 0.1.3-vs-0.2.3 hybrid flag semantics, Kilosort
     4 in place of 2.5, and SI's `margin_ms` default (5 ms in the paper's
     0.97.1, `auto` = 16.7 ms in 0.104.8).

   This is the reproduction contract. Exploratory sweeps are free to do
   whatever is cheap, and must say so.

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
3. `make paper PROFILE=configs/profiles/paper-real-np1-8.yaml` -> reproduces
   Buccino et al. Fig 2/6/7 within the paired tolerance of §5 (median |ratio-1|
   <= 2%, max <= 5%, per recording).
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

- **Primary paper.** Buccino A P, Winter O, Bryant D, Feng D, Svoboda K,
  Siegle J H (2023) *Compression strategies for large-scale
  electrophysiology data*, J. Neural Eng. **20** 056009. Open access,
  CC-BY 4.0. (Article number corrected 2026-08-20 from 056001, which was
  wrong.)
  - DOI / landing: <https://doi.org/10.1088/1741-2552/acf5a4>
  - Article: <https://iopscience.iop.org/article/10.1088/1741-2552/acf5a4>
  - PDF: <https://iopscience.iop.org/article/10.1088/1741-2552/acf5a4/pdf>
  - Supplementary (figures S1-S8, `jneacf5a4supp1.pdf`): reachable from
    <https://iopscience.iop.org/article/10.1088/1741-2552/acf5a4/data>
    (the actual file link is a time-limited signed S3 URL, so it must be
    taken from that page rather than hard-coded)
  - PubMed: <https://pubmed.ncbi.nlm.nih.gov/37651998/>
- **Preprint.** bioRxiv 2023.05.22.541700 v2.
  - DOI: <https://doi.org/10.1101/2023.05.22.541700>
  - Full text: <https://www.biorxiv.org/content/10.1101/2023.05.22.541700v2.full>
  - PDF: <https://www.biorxiv.org/content/10.1101/2023.05.22.541700v2.full.pdf>
- **Benchmark scripts** (produce the results CSVs; MIT):
  <https://github.com/AllenNeuralDynamics/ephys-compression> — the capsule
  pins commit `c89e8e481435f39e3bf041bfc0eaac5ef6d93900`.
- **Analysis capsule** (notebooks that make every figure; MIT, outputs
  stripped in the GitHub mirror):
  <https://github.com/AllenNeuralDynamics/aind-capsule-ephys-compression-results>
  - Code Ocean published capsule id `3822095`, environment image
    `registry.codeocean.com/published/3d64017a-91ab-4e84-b170-5dfa7a4c4046:v2`
  - Exported archive vendored at `src/capsule-ephys-compression-results/`.
    Its `data/` asset (the per-recording results CSVs) is **CC0 1.0**,
    which is why `.specify/specs/paper-reference-lossless.csv` may be
    derived from it and committed here.
- **Benchmark data** (the 16 recordings + MEArec simulations):
  - AWS Open Data registry: <https://registry.opendata.aws/allen-nd-ephys-compression/>
  - Bucket: `s3://aind-ephys-compression-benchmark-data`
  - DataLad mirror we actually use: `///aind-benchmark-data/ephys-compression`
    → <https://datasets.datalad.org/aind-benchmark-data/ephys-compression/>
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
