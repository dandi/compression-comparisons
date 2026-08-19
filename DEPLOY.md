# DEPLOY.md — Running compression-comparisons on a beefier server

This document is the concrete recipe for taking the benchmark off a laptop
and running it against real IBL / AIND recordings on a machine with more
CPU (and, for spike-sorting-in-the-loop cells, a GPU). It picks up right
where the first-run results (`results/dandi-t261-compression-study/derivatives/compbench-2026-08-19-CSHZAD026-slice10s/`)
leave off.

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

```bash
# The STAMPED study (top-level, tiny)
git clone <study-remote> dandi-t261-compression-study
cd dandi-t261-compression-study
datalad get code/compression-comparisons-tools   # the tool code
datalad get -r sourcedata/aind-ephys-compression # register the S3 mirror

# Pull the raw ephys data (this is the slow step — 100s of GB)
# Everything at once:
datalad -C sourcedata/aind-ephys-compression get .
# OR a subset:
datalad -C sourcedata/aind-ephys-compression get ibl-np1  # ~110 GB
datalad -C sourcedata/aind-ephys-compression get aind-np1 # ~135 GB
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

Edit `configs/datasets/aind-ibl-np1-CSHZAD026-slice10s-bp.yaml` (and
similar) to point at the sourcedata paths inside the study:

```yaml
loader: aind-benchmark
params:
  path: ../../sourcedata/aind-ephys-compression/ibl-np1/CSHZAD026_2020-09-04_probe00
  # duration_s:  # unset → encode the full 1200 s recording
preprocessing:
  - kind: bandpass
    low_hz: 300
    high_hz: 6000
    order: 4
```

(The path is relative to the tool checkout at `code/compression-comparisons-tools/`.)

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
walltime seen so far is ~30 s (blosc) to ~600 s (T.261 with QP). At 32
parallel cores, the whole sweep should complete in **4–10 hours**.

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
