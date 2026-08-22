# DEPLOY.md — Running compression-comparisons on a beefier server

This document is the concrete recipe for taking the benchmark off a laptop
and running it against real IBL / AIND recordings on a machine with more
CPU (and, for spike-sorting-in-the-loop cells, a GPU). It picks up right
where the first-run results (`results/dandi-t261-compression-study/derivatives/compbench-2026-08-19-CSHZAD026-slice10s/`)
leave off.

## Current state (2026-08-20)

Three reproductions live under the STAMPED study at
`results/dandi-t261-compression-study/derivatives/` — raw, band-pass,
and band-pass-v2 (round-2 metrics), all on `CSHZAD026` at a 10 s slice.

**The benchmark has been deployed to a second machine** (32-core /
1 TB / 35 TB, no GPU) and the port is documented in §1c. Neither repo
has a git remote on either machine — the transfer was a direct copy —
so the "clone from `<study-remote>`" instructions in §1b remain
aspirational. Pushing both repos somewhere shared is the outstanding
housekeeping item.

## Target hardware

Recommendations for the "full paper reproduction on 16 recordings"
scenario (Buccino et al. Fig 2 & 3):

| Component | Minimum       | Recommended                              | Why                                                                 |
| --------- | ------------- | ---------------------------------------- | ------------------------------------------------------------------- |
| CPU       | 8 cores       | 32–64 cores                              | ~1000-2500 cells per sweep; `--cores N` parallelism (one process per cell) |
| RAM       | 32 GB         | 128 GB                                   | Peak RSS ~3 GB per T.261 cell; large blosc L9 chunks add more       |
| Disk      | 600 GB        | 2 TB                                     | Source data 523 GB + derivatives + a few container images           |
| GPU       | none for §Fig2 | NVIDIA T4 or better for §Fig3           | Only Kilosort4 (lossy spike-sorting eval) needs CUDA                |
| Network   | 100 Mbit/s    | 1 Gbit/s                                 | `datalad get` streams from AWS us-west-2                            |

## Container is the pinned reproducibility target

`containers/compbench-base.Dockerfile` (CPU) and `compbench-ks4.Dockerfile`
(CUDA) build BWC + install compbench + con-duct + wavpack-numcodecs.
Everything below assumes you run inside a container — that's how numbers
stay comparable across machines.

## Step-by-step

### 0. Prerequisites

```bash
sudo apt-get install -y git git-annex podman apptainer   # or docker/singularity
pipx install uv

# datalad is PINNED to the PR #7901 branch, not the distro package: released
# datalad loses `run` records under concurrency and rejects nested runs, so
# per-cell provenance would be silently wrong. Rationale, evidence and the
# repin-on-merge checklist: .specify/specs/datalad-pin.md
uv tool install --force \
  "datalad @ git+https://github.com/datalad/datalad.git@30b6deef70e6808de43c40bfe870462de7ae9373"
```

The sweep scripts refuse to run against any other datalad
(`COMPBENCH_ALLOW_ANY_DATALAD=1` overrides, at the cost of correct records).

**Check the scratch volume before any sweep.**

```bash
make env-info
#   TMPDIR                  = /path/to/compression-comparisons/.tmp
#   /dev/md124   51T   18T   32T  37%  /path/to/compression-comparisons
#   COMPBENCH_BLOSC_THREADS = 1
```

The T.261 adapter round-trips through files, so every in-flight cell holds a
raw + encoded copy of its input on disk: ~1.5 GB per cell at a 60 s slice,
~30 GB per cell at full length. Python sends that to `TMPDIR`, which defaults
to `/tmp` — on a container host that is usually the **root overlay**, shared
and small. On the machine this was first deployed to, `/` had 58 GB free at
96 % capacity while the data volume had 32 TB; a 21-way sweep would have
filled the root filesystem and taken down far more than the sweep.

The committed `.env` therefore sets `COMPBENCH_TMPDIR=.tmp` (repo-relative,
gitignored, resolved to an absolute path). Both `make` and the Snakefile
resolve and create it, so the guarantee holds whether you go through `make`,
call `snakemake` directly, or run inside a container. An explicit `TMPDIR`
already in the environment always wins — set that to node-local scratch on
HPC:

```bash
export TMPDIR=$SLURM_TMPDIR       # or /scratch/$USER/…
```

`.env` also pins `COMPBENCH_BLOSC_THREADS=1` — see §4 "Parallelism".

### 1. Clone the study, the tool, and the source data

**Study repo is not yet on a public remote.** Skip to §1a for the
current transfer recipe. When the study is pushed to GitHub / a DataLad
mirror, §1b below is the future-canonical form (kept here so the
one-command intent is documented).

### 1a. Current: sync from Yaroslav's dev machine

**Two independent clones needed** — the tool repo AND the study repo. The
study lists the tool repo as a subdataset; on the target machine you
re-point that URL at the local tool clone.

```bash
# Clone both from your source (dev machine, GitHub eventually, etc.).
# Since the tool repo has its OWN submodule (src/bwc → HHI GitLab, HTTPS),
# --recursive is safe on it directly.
git clone --recursive <source>/compression-comparisons
git clone <source>/dandi-t261-compression-study

# --- Tool repo setup ---
cd compression-comparisons
# src/bwc came in via --recursive above. If you got the tool clone WITHOUT
# --recursive, run:
#   git submodule update --init --recursive          # HTTPS, no flag needed

# --- Study repo setup ---
cd ../dandi-t261-compression-study

# The tool-code submodule's URL in .gitmodules is Yaroslav's absolute path
# (`/home/yoh/proj/dandi/compression-comparisons`). Repoint it at YOUR
# tool clone BEFORE initialising:
git config submodule.code/compression-comparisons-tools.url $PWD/../compression-comparisons

# Init both submodules. The tool-code one is a local path (file: transport),
# blocked by default since git 2.38.1 (CVE-2022-39253). Two options:
#
#   (A) One-shot allow — narrow blast radius, recommended:
git -c protocol.file.allow=always submodule update --init --recursive
#
#   (B) Persistent per-user opt-in (only allows file: for URLs YOU set via
#       `git config`, NOT for URLs coming from an untrusted .gitmodules):
#     git config --global protocol.file.allow user
#     git submodule update --init --recursive
#
# DO NOT `git config --global protocol.file.allow always` — that turns off
# the CVE-2022-39253 protection everywhere.

# The sourcedata subdataset uses HTTPS (///aind-benchmark-data/ephys-compression)
# so the file: restriction never applies to it. `datalad get` handles all
# this transparently and is the DataLad-idiomatic form:
datalad get sourcedata/aind-ephys-compression   # registers; files still annexed
datalad -C sourcedata/aind-ephys-compression get \
    ibl-np1/CSHZAD026_2020-09-04_probe00/traces_cached_seg0.raw   # ~28 GB, one recording
```

**If you see `fatal: transport 'file' not allowed`**, you hit CVE-2022-39253
hardening on the tool-code submodule's `file:` URL. Use option (A) above.

### 1b. Future canonical (once the study is pushed)

```bash
# --recursive registers subdatasets; annexed files are NOT pulled yet.
datalad clone --recursive <study-remote> dandi-t261-compression-study
cd dandi-t261-compression-study

# Pull raw ephys data — slow step. Subset first:
datalad -C sourcedata/aind-ephys-compression get \
    ibl-np1/CSHZAD026_2020-09-04_probe00/traces_cached_seg0.raw

# Or everything:
datalad -C sourcedata/aind-ephys-compression get .
```

### 1c. Notes from the actual port (2026-08-20)

Four things bit us moving from the laptop to the deploy host. All are
fixed in the tool repo now, but they are what to expect on machine three.

1. **The `sourcedata` subdataset arrived with an empty worktree.** Its
   `.git` copied but its checkout did not, so every file showed as a
   staged deletion and `datalad get` had nothing to resolve. Fix:
   `git -C sourcedata/aind-ephys-compression reset --hard HEAD`, which
   restores the annex symlinks. Verify with `git annex info --fast .` —
   it should report 126 annexed files / 523 GB.

2. **The tool-code submodule pointed `origin` at the source machine's
   absolute path.** Repoint it before checking out the pinned commit:

   ```bash
   cd code/compression-comparisons-tools
   git remote set-url origin /path/to/your/compression-comparisons
   git -c protocol.file.allow=always fetch origin
   git checkout --detach "$(git -C ../.. rev-parse HEAD:code/compression-comparisons-tools)"
   ```

3. **`pip install .[audio]` fails on glibc 2.36.** `wavpack-numcodecs`
   ships prebuilt binaries for glibc 2.35 and 2.39 only, and Debian 12/13
   sits between them:

   ```
   RuntimeError: Could not find a matching the system's glibc version 2.36.
   Available builds: ['2.35', '2.39']
   ```

   **Resolved 2026-08-20 — and the container was never the fix.** The
   glibc check only runs on the fallback branch: `wavpack-numcodecs`
   links a *system* libwavpack whenever a `wavpack` binary is on PATH.
   AIND's own `aind-ephys-pipeline-base` is glibc **2.31** (verified by
   pulling it), so it misses 2.35/2.39 exactly as our 2.36 and 2.41 hosts
   did — the container recipe previously recommended here could not have
   worked.

   Build it instead (no root needed):

   ```bash
   make wavpack        # -> vendor/wavpack, via scripts/build_wavpack.sh
   export LD_LIBRARY_PATH="$PWD/vendor/wavpack/lib:$LD_LIBRARY_PATH"
   uv pip install --python .venv/bin/python wavpack-numcodecs
   ```

   `make` and the Snakefile export both paths for you. Note the extension
   compiles from source, so it needs `Python.h`: if the distro has no
   `python3-dev`, build the venv on a uv-managed CPython, which ships
   headers. Distro packages (`wavpack`, `libwavpack-dev`) are preferred
   where available.

4. **`numcodecs` must stay below 0.16.** 0.16 removed
   `numcodecs.blosc.cbuffer_sizes`, which `zarr` 2.x imports at module
   load — so `import zarr`, `import spikeinterface`, and every dataset
   loader died on a fresh resolve. Now pinned in `pyproject.toml`; if you
   are installing from an older checkout, add `numcodecs<0.16` by hand.

### 2. Build the container image

```bash
cd code/compression-comparisons-tools

# Docker/Podman path
podman build -t compbench-base:local -f containers/compbench-base.Dockerfile .

# Apptainer/HPC path (converts the OCI image to a .sif)
./containers/to_apptainer.sh compbench-base:local
# → compbench-base.sif (~5–8 GB)
```

For Kilosort4 GPU work (Phase 3 spike-sorting eval, not required for Fig 2):

```bash
podman build -t compbench-ks4:local -f containers/compbench-ks4.Dockerfile .
./containers/to_apptainer.sh compbench-ks4:local
```

### 3. Pick a profile

Two profiles cover the paper reproduction. Neither needs a hand-written
dataset YAML — both use the `datasets_matrix:` block, which
cross-products a recording list with a preprocessing list and
materialises the expanded YAMLs into
`<results_dir>/generated-datasets/` as run provenance.

| Profile | Scope | Cells | Wall (32-core) |
| ------- | ----- | ----: | -------------- |
| `configs/profiles/paper-real-np1-8.yaml` | 8 NP1 x {raw, bp, lsb, lsbbp} x 44 codec configs, 60 s slice | 1056 | ~12 h |
| `configs/profiles/paper-real-16.yaml` | all 16 recordings, same conditions, full length | 2464 | ~days |
| `configs/profiles/paper-real.yaml` | single recording (CSHZAD026), 10 s — smoke/verify | 21 | ~35 min |

**Run `paper-real-np1-8` first.** The revised Phase 1 gate (plan §5) is a
*median-of-8* comparison against the paper's median-of-8, so it needs
breadth across recordings rather than length within one — a single
recording at full length is still one point in the paper's distribution.
If the codec ranking comes out wrong, you want to know that after 5 hours,
not 5 days. `paper-real-16` then confirms duration-invariance and covers
NP2.

To add recordings or preprocessing variants, edit the profile's
`datasets_matrix:` block — no Python and no new dataset YAMLs:

```yaml
datasets_matrix:
  loader: aind-benchmark
  params: {start_s: 0.0, duration_s: 60.0}   # drop duration_s for full length
  recordings:
    - {label: ibl-CSHZAD026, params: {path: sourcedata/aind-ephys-compression/ibl-np1/CSHZAD026_2020-09-04_probe00}}
  preprocessing:
    - {label: raw}
    - {label: bp, steps: [{kind: bandpass, low_hz: 300, high_hz: 6000, order: 4}]}
```

The older single-dataset YAMLs (`configs/datasets/*-sourcedata.yaml`)
still work and are still what `paper-real.yaml` uses.

### 4. Run the sweep

**Always run from the STAMPED study root.** That is what makes
`sourcedata/...` inside each dataset resolve and what puts results in the
study's `derivatives/` tree. Relative dataset paths inside a profile are
anchored at the profile file, not at your CWD, so this works from
anywhere.

```bash
# Under the study repo (so paths in results/ land in the right place):
cd ../..
PROFILE=code/compression-comparisons-tools/configs/profiles/paper-real-np1-8.yaml
OUT=derivatives/compbench-$(date -I)-np1-8-slice60s

# Podman/Docker: bind-mount the study, launch the sweep
podman run --rm -v $PWD:/work -w /work compbench-base:local bash -c "
  snakemake -s code/compression-comparisons-tools/src/compbench/pipeline/Snakefile \
      --configfile $PROFILE \
      --config results_dir=$OUT \
      --cores 21 --keep-going
"

# Apptainer/HPC: same shape
apptainer exec --bind $PWD:/work --pwd /work compbench-base.sif \
  snakemake -s code/compression-comparisons-tools/src/compbench/pipeline/Snakefile \
      --configfile $PROFILE \
      --config results_dir=$OUT \
      --cores 21 --keep-going

# Host-native (no container) — needs the venv from §0 and a built src/bwc:
snakemake -s code/compression-comparisons-tools/src/compbench/pipeline/Snakefile \
    --configfile $PROFILE --config results_dir=$OUT --cores 21 --keep-going

# The AWS S3 read path in the sourcedata subdataset needs network from inside
# the container. Bind-mount your ~/.aws or the pre-fetched data locally if
# your compute nodes don't have outbound network (typical on HPC).
```

**Pick `--cores` from memory, not core count**, for full-length runs — see
scale wall 3 below. At a 60 s slice, 21-way is comfortable on 128 GB; at
1200 s budget ~60 GB per concurrent cell.

#### Parallelism

The sweep parallelises **across the matrix, not within a cell**. Snakemake
schedules one `run_cell` job per (dataset x codec x chunking) combination and
runs `--cores N` of them concurrently; each job is one `duct compbench run`
process that declares `threads: 1`. Cells are fully independent — no barrier,
no shared state — so a 1056-cell sweep is 1008 single-core jobs, N at a time,
and `--keep-going` means one timeout costs one cell.

That accounting is only honest if the codecs stay single-threaded, and blosc
does not by default:

- **blosc defaults to 8 threads.** At `--cores 21` that is ~168 threads on a
  32-core box. Every cell then competes with its neighbours, and `wall_s`,
  `enc_xRT` and `dec_xRT` become functions of how many other cells happened to
  be running — not reproducible even on the same host at a different `--cores`.
- **Multi-threaded blosc is not byte-reproducible.** Above one thread the same
  input yields a different compressed byte stream on every run. The encoded
  *length* is stable, so CR — the headline metric — is unaffected and
  round-trip stays exact, but the artifact itself differs run to run.

`.env` pins `COMPBENCH_BLOSC_THREADS=1`, the Snakefile exports it into every
cell, and each cell's `manifest.json` records the value under
`codec.blosc_nthreads`. Set it higher only to reproduce a deliberate
in-codec-threading throughput measurement.

The one thing that is *not* parallel is the aggregation: `compbench report`
runs once at the end via Snakemake's `onsuccess`/`onerror` hook, walking every
`metrics.json`. That is seconds, even at 1008 cells.

**Wall-time budget.** Measured per-cell wall times on a 10 s slice of
CSHZAD026 (384 ch, band-pass), from the v2 derivative's `report.parquet`:

| Cell class                        | 10 s      | x120 → 1200 s |
| --------------------------------- | --------: | ------------: |
| T.261 lossy (QP 1.5-8)            | 378-578 s |     13-19 h   |
| zstd L22                          |     331 s |        11 h   |
| lzma preset 6                     |     275 s |         9 h   |
| T.261 IndepChannel lossless       |     175 s |         6 h   |
| blosc-zlib L9                     |      59 s |         2 h   |
| everything else (blosc, gzip, lz4)|   13-35 s |     0.4-1.2 h |
| T.261 joint-channel lossless      | >30 min (timeout) | 60+ h |

Scale linearly in duration and multiply by the cell count. That is where
the ~5 h / ~5 day figures in §3 come from.

**Note on `--keep-going`:** the Makefile's `paper` / `full` targets pass
`--keep-going` by default so a single failed cell (T.261 timeout, OOM)
doesn't block the report of the remaining cells. The aggregator uses
`rglob("metrics.json")` and tolerates missing cells.

**Known scale walls (from R5 reviewer, 2026-08-19; status 2026-08-20):**

1. ~~**Bandpass at 1200 s OOMs on <200 GB RAM boxes.**~~ **Fixed**
   ([R5-C1]). `preprocessing._bandpass` now filters in channel blocks
   sized by `max_block_bytes` (default 2 GiB). Exact, not approximate:
   filtfilt runs along the time axis independently per channel, so a
   channel block is bit-identical to the whole-array call. Peak is now a
   few GB instead of 200-250 GB.
2. **T.261 joint-channel EEG lossless times out.** Still open ([R5-C2]).
   Even at 10 s it exceeds 30 min; at 1200 s expect 60+ hours per cell.
   It is deliberately **omitted from `paper-real-np1-8.yaml` and
   `paper-real-16.yaml`** — re-add once the Phase 2b in-process wrapper
   or channel-group chunking lands.
3. ~~**Memory-bound parallelism.**~~ **Largely fixed** ([R5-H2]). The
   wall was the metric pass, not the codec: `run_cell` promoted both the
   original and the reconstruction to float64 and handed those to five
   independent metric functions, ~500 GB peak for one 1200 s lossy cell.
   `metrics.distortion_summary()` now accumulates every statistic in
   bounded blocks, and `manifest.array_digest` streams instead of calling
   `tobytes()`. A 1200 s cell now holds its int16 input plus
   reconstruction (~55 GB) and a few GB of metric blocks. Budget ~60 GB
   per concurrent full-length cell; on 1 TB that is ~12-16 way, so cap
   `--cores` accordingly rather than at the core count.
4. **`datasets_matrix:` replaces the 48-YAML problem** ([R5-H1], fixed).
   See §3.

**Adding the joint-channel T.261 lossless cell:** on 384 ch × 10 s data
this cell exceeds 30 min. On 384 ch × 1200 s (full recording) it will
be much longer. Either bump `timeout` in `src/compbench/codecs/t261.py`
(and rebuild the container), OR wait for the Phase 2b in-process pybind11
wrapper (~2–5× faster), OR chunk the input by channel-group.

### 5. Aggregate the sweep + regenerate the Markdown table

```bash
# From inside the container, or from a checkout with compbench installed:
compbench report \
    --results-dir derivatives/compbench-$(date -I) \
    --output derivatives/compbench-$(date -I)/report.parquet

compbench render-report \
    --parquet derivatives/compbench-$(date -I)/report.parquet \
    --output derivatives/compbench-$(date -I)/AUTO_TABLE.md \
    --title "Compression benchmark — $(date -I)" \
    --source-note "See RESULTS.md for narrative discussion. Rendered from report.parquet."
```

**The Markdown table is idempotent.** Add new cells (any dataset ×
codec combination), re-run these two commands, and `AUTO_TABLE.md`
regenerates with the new rows. Sorted by CR descending, best-lossless
and best-lossy highlighted, formatting stable across runs.

### 6. Save the derivative into the study

```bash
cd path/to/dandi-t261-compression-study
datalad save -m "Sweep $(date -I): paper-real profile on N recordings" \
    derivatives/compbench-$(date -I)
```

`datalad save` snapshots the whole subtree; `datalad push` sends it
back to any configured remote.

## Verifying results across machines

Any two runs of the same profile against the same input data on
different hardware should produce **identical CR + RMSE + round-trip-OK
columns** in `report.parquet`. The `wall_s`, `enc_xRT`, `dec_xRT`, and
`RSS GB` columns will differ (hardware-dependent). To spot-check
determinism:

```bash
compbench report --results-dir <run1> --output /tmp/r1.parquet
compbench report --results-dir <run2> --output /tmp/r2.parquet
python -c "
import pyarrow.parquet as pq
a = pq.read_table('/tmp/r1.parquet').to_pandas().set_index('cell_dir')
b = pq.read_table('/tmp/r2.parquet').to_pandas().set_index('cell_dir')
for col in ('metric_cr','metric_rmse','metric_round_trip_ok'):
    diff = (a[col] - b[col]).abs().max() if a[col].dtype != 'object' else 'skip'
    print(col, diff)
"
```

## Continuing after handoff

The scenario you asked about — "I populate more results, will the table
re-render?" — is handled entirely by steps 4-5. Concretely:

1. Add more `configs/datasets/*.yaml` files (one per recording, or one
   per dataset variant like raw vs band-pass).
2. Extend `configs/profiles/paper-real.yaml`'s `datasets:` list with them.
3. Rerun step 4 — Snakemake picks up only the missing cells, doesn't
   re-run completed ones (dep-graph based on output files).
4. Rerun step 5 — `AUTO_TABLE.md` regenerates with all cells to date.

Optional: wrap steps 4-5 in a `Makefile` target or a `datalad run`
invocation for full provenance capture.

## Open items (2026-08-20)

Things a fresh deployment will run into that are *not* fixed in code.

- **Spike-sorting fidelity: GPU now available, pipeline still to build.**
  A CUDA host (A100-PCIE-40GB, driver 590.48.01, CUDA 13.1) was attached
  2026-08-20 and the full path is verified end to end: MEArec ->
  band-pass -> Kilosort4 on GPU -> `GroundTruthComparison`, 60 s x 384 ch
  in 130 s (0.46x realtime), accuracy 0.785 / precision 0.790 / recall
  0.854 against the 100 ground-truth units. Install with the new
  `[sorting]` extra.

  Still missing: `compbench.metrics.sorting` is a contract-only skeleton,
  the `compbench sort` / `compare-sorting` CLI subcommands don't exist,
  and `configs/profiles/sorting-eval.yaml` has never run. Nothing in
  Phase 3a (Fig 2 / Fig 7) needs a GPU.

- **The GPU host is a different image — expect a rebuild.** Attaching the
  GPU swapped the base image: Debian 12 -> 13 (trixie), glibc 2.36 ->
  2.41, Python 3.11 -> 3.13, and `cmake` / `datalad` / `apptainer` are
  gone. The `.venv` built against 3.11 dies with a dangling
  `python -> /usr/bin/python3.11` symlink; rebuild it (`uv venv --python
  3.13 && uv pip install -e '.[devel,ephys,pipeline,sorting]'`) and
  reinstall datalad (the pinned build — see Prerequisites). Prebuilt `src/bwc/bin/`
  binaries survive the move and still run, so BWC does not need cmake
  again unless you change it. All 354 tests pass on 3.13.

  Note glibc 2.41 does not match WavPack's bundled builds (2.35 / 2.39)
  either — but that is no longer a blocker, and no container is needed;
  see §1c item 3.
- ~~**The paper's per-recording numbers aren't ingested.**~~ **Resolved
  2026-08-20.** The Code Ocean capsule is exportable and its `data/` asset
  is CC0; it is vendored at `src/capsule-ephys-compression-results/`.
  Per-recording results for the lossless, delta, preprocessing, lossy-sim
  and lossy-exp benchmarks are all local, and
  `.specify/specs/paper-reference-lossless.csv` is derived from them.
  No account is required.
- ~~**WavPack needs the container.**~~ **Resolved** — it needs a system
  libwavpack on PATH, not a particular glibc. `make wavpack` builds one
  without root; see §1c item 3. (WavPack is the paper's best *lossless*
  codec; WavPack **Hybrid** is its lossy one.)
- **The chunk-size axis is missing** ([R1-M4], [R5-M4]). The paper's
  Fig 2/Fig 7 average over chunk sizes 0.1 / 1 / 10 s as well as shuffle
  variants. Our adapters compress whole buffers, so only the shuffle and
  level axes are swept. This makes our per-codec medians comparable in
  *ranking* but not exactly in *level* to the paper's.
- **Neither repo has a git remote.** Both machines hold independent
  copies with no shared push path.
- **T.261 joint-channel lossless is excluded from the paper profiles.**
  See scale wall 2 in §4.

## Troubleshooting

- **`datalad get` throughput:** measured **~40 MB/s** sustained from the
  `s3-bucket` special remote on a well-connected US East host with
  `datalad get -J4` — 27.6 GB (one IBL recording) in 11.6 min, so the
  whole 523 GB lands in ~3.7 h. If you see the ~5 MB/s that earlier notes
  warned about, you are being rate-limited on the `--no-sign-request`
  path: use an AWS-authenticated request (still free from Open Data
  buckets), or run in us-west-2 (bucket region).
- **`WorkflowError: codec X not registered`:** an optional dependency is
  missing. For `wavpack`, run `make wavpack` and make sure
  `LD_LIBRARY_PATH` includes `vendor/wavpack/lib` — a vendored libwavpack
  the loader cannot see is indistinguishable from an uninstalled codec,
  and the Snakefile now says so explicitly when it detects that case.
  Verify with `compbench list-codecs`.
- **T.261 encode hits the 30-min timeout:** joint-channel lossless on
  wide (384 ch) inputs is known-slow. See §"Adding the joint-channel
  T.261 lossless cell" above.
- **con-duct spins forever with `Sample interval: 0.5 is below 1.0s
  and may behave erratically`:** raise `--sample-interval 1` in the
  Snakefile's shell block. Not a functional bug, just a warning.
