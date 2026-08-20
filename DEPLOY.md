# DEPLOY.md — Running compression-comparisons on a beefier server

This document is the concrete recipe for taking the benchmark off a laptop
and running it against real IBL / AIND recordings on a machine with more
CPU (and, for spike-sorting-in-the-loop cells, a GPU). It picks up right
where the first-run results (`results/dandi-t261-compression-study/derivatives/compbench-2026-08-19-CSHZAD026-slice10s/`)
leave off.

## Current state (2026-08-19)

Two working reproductions live under the STAMPED study at
`results/dandi-t261-compression-study/derivatives/` — raw and
band-pass, both on `CSHZAD026` at 10 s slice. Neither the study repo
nor the tool repo has been pushed to any remote yet, so the "clone from
`<study-remote>`" instructions in §1 below are aspirational — until
someone pushes, the study exists only on Yaroslav's dev machine. If
you're deploying elsewhere, use the sync approach in §1a below.

## Target hardware

Recommendations for the "full paper reproduction on 16 recordings"
scenario (Buccino et al. Fig 2 & 3):

| Component | Minimum       | Recommended                              | Why                                                                 |
| --------- | ------------- | ---------------------------------------- | ------------------------------------------------------------------- |
| CPU       | 8 cores       | 32–64 cores                              | 21 codec cells × 16 recordings = 336 cells; `--cores N` parallelism |
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
sudo apt-get install -y git datalad git-annex podman apptainer   # or docker/singularity
pipx install uv
```

### 1. Clone the study, the tool, and the source data

**Study repo is not yet on a public remote.** Skip to §1a for the
current transfer recipe. When the study is pushed to GitHub / a DataLad
mirror, §1b below is the future-canonical form (kept here so the
one-command intent is documented).

### 1a. Current: sync from Yaroslav's dev machine

```bash
# On the dev machine (study at ~/proj/dandi/compression-comparisons/results/dandi-t261-compression-study):
tar czf /tmp/study.tar.gz -C ~/proj/dandi/compression-comparisons/results dandi-t261-compression-study

# On the target machine:
scp yaroslav@dev:/tmp/study.tar.gz . && tar xzf study.tar.gz && cd dandi-t261-compression-study

# The tool-code submodule currently points at a local absolute path — fix
# to the GitHub URL (when the tool repo is pushed) or another host you have:
git -c protocol.file.allow=always submodule sync
git config submodule.code/compression-comparisons-tools.url https://github.com/dandi/compression-comparisons
datalad get -r code/compression-comparisons-tools

# sourcedata subdataset points at ///aind-benchmark-data/ephys-compression (public):
datalad get sourcedata/aind-ephys-compression   # registers; files still annexed
datalad -C sourcedata/aind-ephys-compression get \
    ibl-np1/CSHZAD026_2020-09-04_probe00/traces_cached_seg0.raw   # ~28 GB, one recording
```

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

### 3. Point profiles at the real data

Use the `-sourcedata` variant of the dataset YAMLs — they point at
paths relative to the STAMPED study root (`sourcedata/aind-ephys-compression/...`):

- `configs/datasets/aind-ibl-np1-CSHZAD026-slice10s-sourcedata.yaml` — raw
- `configs/datasets/aind-ibl-np1-CSHZAD026-slice10s-bp-sourcedata.yaml` — band-pass

Then edit `configs/profiles/paper-real.yaml`'s `datasets:` list to
reference the `-sourcedata` variant instead of the dev-machine scratch
path. To encode the full 1200 s recording (paper setting) instead of
the 10 s slice, drop the `duration_s` field from the dataset YAML.

For the paper-comparable full sweep, add one dataset YAML per recording
under `configs/datasets/` and reference them all in
`configs/profiles/paper-real.yaml`. A small helper is on the roadmap;
until then, `for` loops over template YAMLs work fine.

### 4. Run the sweep

Inside the container, with your desired parallelism:

```bash
# Under the study repo (so paths in results/ land in the right place):
cd ../..

# Podman/Docker: bind-mount the study, launch the sweep
podman run --rm -v $PWD:/work -w /work compbench-base:local bash -c '
  snakemake -s code/compression-comparisons-tools/src/compbench/pipeline/Snakefile \
      --configfile code/compression-comparisons-tools/configs/profiles/paper-real.yaml \
      --config results_dir=derivatives/compbench-$(date -I) \
      --cores 32
'

# Apptainer/HPC: same shape
apptainer exec --bind $PWD:/work --pwd /work compbench-base.sif \
  snakemake -s code/compression-comparisons-tools/src/compbench/pipeline/Snakefile \
      --configfile code/compression-comparisons-tools/configs/profiles/paper-real.yaml \
      --config results_dir=derivatives/compbench-$(date -I) \
      --cores 32

# The AWS S3 read path in the sourcedata subdataset needs network from inside
# the container. Bind-mount your ~/.aws or the pre-fetched data locally if
# your compute nodes don't have outbound network (typical on HPC).
```

**Wall-time budget:** 16 recordings × 21 cells = 336 cells. Median cell
walltime on 10 s slices was ~30 s (blosc) to ~600 s (T.261 with QP). At
1200 s slices (paper setting) each T.261 cell scales ~120× → hours per
cell. See §"Known scale walls" below for the realistic numbers and
required mitigations before running at 1200 s.

**Note on `--keep-going`:** the Makefile's `paper` / `full` targets pass
`--keep-going` by default so a single failed cell (T.261 timeout, OOM)
doesn't block the report of the remaining cells. The aggregator uses
`rglob("metrics.json")` and tolerates missing cells.

**Known scale walls (from R5 reviewer, 2026-08-19):**

1. **Bandpass at 1200 s OOMs on <200 GB RAM boxes.** `filtfilt` on 27 GB
   int16 promotes to 110 GB float64 + internal buffers → ~200-250 GB
   peak. Mitigation not landed yet — chunk-along-channels or use
   `sosfiltfilt` on float32.
2. **T.261 joint-channel EEG lossless times out.** Even at 10 s it
   exceeds 30 min. At 1200 s it's likely 60+ hours per cell. Exclude
   from `paper-real.yaml` or chunk by channel-group until Phase 2b
   pybind11 wrapper is ready.
3. **Memory-bound parallelism.** Peak RSS per 10 s cell is 2-3 GB; at
   1200 s expect 24-30 GB. On c7i.16xl (128 GB) only ~4 cells run in
   parallel. Use r7i.16xl (512 GB) for effective 17-way parallelism.

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

## Troubleshooting

- **`datalad get` is slow (~5 MB/s):** you're hitting S3 rate-limits from
  the AWS `--no-sign-request` path. Options: use an AWS-authenticated
  request (still free from Open Data buckets), or run on an AWS instance
  in us-west-2 (bucket region) for near-line-rate transfers.
- **`WorkflowError: codec X not registered`:** the container was built
  without an optional dep. `[audio]` (wavpack) is glibc-sensitive but
  works in the AIND-base image; verify with
  `podman run compbench-base:local compbench list-codecs`.
- **T.261 encode hits the 30-min timeout:** joint-channel lossless on
  wide (384 ch) inputs is known-slow. See §"Adding the joint-channel
  T.261 lossless cell" above.
- **con-duct spins forever with `Sample interval: 0.5 is below 1.0s
  and may behave erratically`:** raise `--sample-interval 1` in the
  Snakefile's shell block. Not a functional bug, just a warning.
