> **STATUS (2026-08-20): these images have never been built or run.**
> No number in this study was produced in a container, and the
> `container:` directive in the Snakefile is commented out. An earlier
> claim that the AIND base image carries a WavPack-compatible glibc was
> **false** — it is glibc 2.31, and WavPack's bundled builds are 2.35 /
> 2.39. WavPack is instead handled natively via `make wavpack`.
>
> Reproducible, digest-pinned per-codec images are planned as Phase 4.5
> of the plan, with the image digest recorded in each cell's manifest.

# Containers

Three images, all derived from the AIND ephys-pipeline images published to
`ghcr.io/allenneuraldynamics/…`, so we inherit their exact SpikeInterface +
preprocessing environment:

| Image             | Base                                                     | GPU? | Used for                                            |
| ----------------- | -------------------------------------------------------- | ---- | --------------------------------------------------- |
| `compbench-base`  | `aind-ephys-pipeline-base:si-0.103.0`                    | No   | Every compression cell (encode/decode/eval)         |
| `compbench-ks25`  | `aind-ephys-spikesort-kilosort25:si-0.103.0`             | No   | Paper-reproduction lossy cells (Kilosort 2.5)       |
| `compbench-ks4`   | `aind-ephys-spikesort-kilosort4:si-0.103.0`              | **Yes (CUDA)** | New-dataset lossy cells (Kilosort 4)      |

The per-step split means the plain compression sweep (which is the bulk of
Buccino et al. Fig 2/3) never pays the GPU-image pull/size cost. Only the
lossy-sort-in-the-loop cells pull the sorter image.

## Building — Docker / Podman

Podman and Docker consume the same Dockerfiles. From the repo root:

```bash
# One image at a time:
podman build -t compbench-base:local -f containers/compbench-base.Dockerfile .
podman build -t compbench-ks25:local -f containers/compbench-ks25.Dockerfile .
podman build -t compbench-ks4:local  -f containers/compbench-ks4.Dockerfile  .

# Or all three:
./containers/build.sh                    # uses podman by default
CONTAINER_ENGINE=docker ./containers/build.sh
```

## Building — Apptainer / Singularity (HPC)

Apptainer can build directly from a Dockerfile using its native format:

```bash
apptainer build compbench-base.sif containers/compbench-base.Dockerfile
```

Or convert an already-built OCI image (from `podman build`) into a `.sif`:

```bash
./containers/to_apptainer.sh compbench-base:local     # → compbench-base.sif
./containers/to_apptainer.sh compbench-ks25:local
./containers/to_apptainer.sh compbench-ks4:local
```

## Running a single cell

The `run.sh` helper picks whichever runtime is available (podman > docker > apptainer):

```bash
./containers/run.sh compbench-base:local \
    duct compbench run --input synthetic:duration_s=1 --codec blosc-zstd \
        --output-dir /work/results/x
```

By default it bind-mounts the repo root as `/work`.

## Snakemake integration (Phase 1+)

Snakemake rules will declare their container via `container: "docker://…"`.
Running with `snakemake --use-apptainer` transparently handles conversion to
`.sif` on HPC; `--use-singularity` is a legacy alias. `--use-podman` /
`--use-docker` work on developer laptops with the same rule text — no changes
needed per runtime.
