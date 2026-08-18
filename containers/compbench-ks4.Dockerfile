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

RUN apt-get update && apt-get install -y --no-install-recommends cmake g++ make git \
    && rm -rf /var/lib/apt/lists/*
COPY src/bwc /opt/bwc
RUN cmake -S /opt/bwc -B /opt/bwc/build \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_CXX_FLAGS="-Wno-restrict" \
    && cmake --build /opt/bwc/build -j$(nproc) \
    && test -x /opt/bwc/bin/release/EncoderApp
ENV BWC_BIN_DIR=/opt/bwc/bin/release
ENV BWC_CFG_DIR=/opt/bwc/cfg

COPY pyproject.toml README.md LICENSE /opt/compbench/
COPY src/compbench /opt/compbench/src/compbench
RUN pip install --no-cache-dir /opt/compbench 'con-duct>=0.7' 'wavpack-numcodecs>=0.2'

RUN compbench --version \
    && compbench list-codecs | grep -qx t261 \
    && duct --version

ENTRYPOINT []
CMD ["/bin/bash"]
