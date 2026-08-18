# compbench-ks4 — CUDA image with Kilosort 4 for lossy-evaluation cells using
# the newer default sorter. Required for `configs/profiles/full.yaml` runs.
#
# Requires an NVIDIA GPU + nvidia-container-toolkit (docker/podman) or
# `--nv` flag (apptainer/singularity) at runtime.

ARG AIND_TAG=si-0.103.0
FROM ghcr.io/allenneuraldynamics/aind-ephys-spikesort-kilosort4:${AIND_TAG}

LABEL org.opencontainers.image.title="compbench-ks4"
LABEL org.opencontainers.image.description="Compression benchmark + Kilosort 4 (CUDA)"
LABEL org.opencontainers.image.source="https://github.com/dandi/compression-comparisons"
LABEL org.opencontainers.image.licenses="MIT"

COPY pyproject.toml README.md LICENSE /opt/compbench/
COPY src/compbench /opt/compbench/src/compbench
RUN pip install --no-cache-dir /opt/compbench 'con-duct>=0.7' 'wavpack-numcodecs>=0.2'

RUN compbench --version && duct --version

ENTRYPOINT []
CMD ["/bin/bash"]
