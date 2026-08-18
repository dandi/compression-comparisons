# compbench-base — CPU-only image for compression cells (no spike-sorting).
#
# Derived from AIND's ephys-pipeline base image so we inherit the exact
# SpikeInterface + preprocessing environment AIND publishes. Adds our CLI
# (`compbench`), con-duct (resource profiler), and third-party numcodecs
# codecs (WavPack in Phase 1, T.261 in Phase 2).
#
# Bump `AIND_TAG` when we upgrade SpikeInterface; upstream tags follow the
# pattern `si-<spikeinterface-version>`.
#
# Build:
#   podman build -t compbench-base:local -f containers/compbench-base.Dockerfile .
#   # or:  docker build …
#   # or:  apptainer build compbench-base.sif containers/compbench-base.Dockerfile
#
# Run:
#   podman run --rm -v $PWD:/work -w /work compbench-base:local \
#       duct compbench run --input synthetic:duration_s=1 --codec blosc-zstd \
#             --output-dir /work/results/x

ARG AIND_TAG=si-0.103.0
FROM ghcr.io/allenneuraldynamics/aind-ephys-pipeline-base:${AIND_TAG}

LABEL org.opencontainers.image.title="compbench-base"
LABEL org.opencontainers.image.description="Compression benchmark base — CPU-only cells"
LABEL org.opencontainers.image.source="https://github.com/dandi/compression-comparisons"
LABEL org.opencontainers.image.licenses="MIT"

# Install compbench + con-duct + Phase 1 audio codecs.
# --no-cache-dir keeps the layer small; the base image already has numpy/numcodecs.
COPY pyproject.toml README.md LICENSE /opt/compbench/
COPY src/compbench /opt/compbench/src/compbench
RUN pip install --no-cache-dir /opt/compbench 'con-duct>=0.7' 'wavpack-numcodecs>=0.2'

# Sanity check at build time — fails the build if the CLI can't start.
RUN compbench --version && compbench list-codecs && duct --version

ENTRYPOINT []
CMD ["/bin/bash"]
