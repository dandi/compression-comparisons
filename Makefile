# compression-comparisons — top-level entry points.
#
# Everything below is a thin driver over `tox` (test/lint/type) or over
# `duct compbench …` (benchmark cells). Snakemake orchestration lives under
# `src/compbench/pipeline/` and is invoked by `make paper` / `make full`
# (added in Phase 1).

PYTHON      ?= python3
UV          ?= uv
RESULTS_DIR ?= results/smoke
SMOKE_CELL  ?= $(RESULTS_DIR)/blosc-zstd-l3

# Committed environment (see .env). `-include` so a stripped checkout still
# builds; the defaults below match the file.
-include .env
export

REPO_ROOT   := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
COMPBENCH_TMPDIR         ?= .tmp
COMPBENCH_BLOSC_THREADS  ?= 1
COMPBENCH_WAVPACK_PREFIX ?= vendor/wavpack

# Codec subprocesses stage raw + encoded copies through TMPDIR; the default
# /tmp is usually the small root overlay on a container host. Resolve to an
# absolute path on the same volume as the repo and make sure it exists.
TMPDIR := $(abspath $(if $(patsubst /%,,$(COMPBENCH_TMPDIR)),$(REPO_ROOT)/$(COMPBENCH_TMPDIR),$(COMPBENCH_TMPDIR)))
export TMPDIR
export COMPBENCH_BLOSC_THREADS

# WavPack: `wavpack-numcodecs` links against the system library only when a
# `wavpack` binary is on PATH — otherwise it demands an exact glibc match that
# no host here satisfies. See .env.
WAVPACK_PREFIX := $(abspath $(if $(patsubst /%,,$(COMPBENCH_WAVPACK_PREFIX)),$(REPO_ROOT)/$(COMPBENCH_WAVPACK_PREFIX),$(COMPBENCH_WAVPACK_PREFIX)))
ifneq ($(wildcard $(WAVPACK_PREFIX)/bin/wavpack),)
  export PATH := $(WAVPACK_PREFIX)/bin:$(PATH)
  export LD_LIBRARY_PATH := $(WAVPACK_PREFIX)/lib:$(LD_LIBRARY_PATH)
endif

.PHONY: wavpack
wavpack:
	@scripts/build_wavpack.sh

.PHONY: scratchdir
scratchdir:
	@mkdir -p "$(TMPDIR)"

.PHONY: env-info
env-info: scratchdir
	@echo "TMPDIR                  = $(TMPDIR)"
	@df -h "$(TMPDIR)" | tail -1
	@echo "COMPBENCH_BLOSC_THREADS = $(COMPBENCH_BLOSC_THREADS)"
	@echo "WAVPACK_PREFIX          = $(WAVPACK_PREFIX) ($(if $(wildcard $(WAVPACK_PREFIX)/bin/wavpack),found,MISSING - run 'make wavpack'))"

.DEFAULT_GOAL := help

.PHONY: help
help:
	@echo "Targets:"
	@echo "  env-info        - show resolved TMPDIR + blosc threads and free space"
	@echo "  wavpack         - build libwavpack into vendor/ (needed for the wavpack codec)"
	@echo "  install         - create .venv and install compbench in devel mode"
	@echo "  test            - unit tests (tox -e py311)"
	@echo "  lint            - ruff check + format-check (tox -e lint)"
	@echo "  type            - mypy strict (tox -e type)"
	@echo "  cov             - unit tests + coverage (tox -e cov)"
	@echo "  integration     - end-to-end tests (tox -e integration)"
	@echo "  smoke           - one duct-wrapped compbench cell + report; < 5 s"
	@echo "  snakemake-smoke - same via the full Snakemake DAG on smoke.yaml"
	@echo "  paper           - PROFILE=... — Snakemake sweep on a profile YAML"
	@echo "  full            - PROFILE=... — same as `paper' but --cores 8 default"
	@echo "  containers      - build all three compbench-* container images"
	@echo "  containers-apptainer - convert built images to .sif for HPC"
	@echo "  clean           - remove .venv, .tox, build/, results/"

.PHONY: install
install:
	$(UV) venv --python 3.11
	. .venv/bin/activate && $(UV) pip install -e '.[devel]'

.PHONY: test lint type cov integration
test:
	tox -e py311
lint:
	tox -e lint
type:
	tox -e type
cov:
	tox -e cov
integration: scratchdir
	tox -e integration

.PHONY: smoke
smoke: scratchdir
	@rm -rf $(SMOKE_CELL)     # idempotent — duct refuses to overwrite existing output-prefix files
	@mkdir -p $(SMOKE_CELL)
	duct \
	    --output-prefix "$(SMOKE_CELL)/duct-" \
	    --sample-interval 1 \
	    --report-interval 1 \
	    compbench run \
	        --input   synthetic:duration_s=0.5,sample_rate_hz=2000,n_channels=4,seed=1 \
	        --codec   blosc-zstd \
	        --codec-params level=3,shuffle=byte \
	        --output-dir $(SMOKE_CELL)
	compbench report --results-dir $(RESULTS_DIR) --output $(RESULTS_DIR)/report.jsonl
	@echo "--- report.jsonl ---"
	@cat $(RESULTS_DIR)/report.jsonl
# Note: `make smoke` requires `duct` (in `[devel]` extra) and `compbench` on PATH.
# Uses `synthetic:` dataset — no external files.

.PHONY: render-report
render-report:
	@[ -f "$${PARQUET:-}" ] || (echo 'usage: make render-report PARQUET=results/.../report.parquet OUT=RESULTS.md' && exit 1)
	compbench render-report --parquet "$$PARQUET" --output "$${OUT:-AUTO_TABLE.md}" $${TITLE:+--title "$$TITLE"}

.PHONY: paper full snakemake-smoke
snakemake-smoke: scratchdir
	snakemake -s src/compbench/pipeline/Snakefile \
	    --configfile configs/profiles/smoke.yaml \
	    --config results_dir=results/smoke-snakemake \
	    --cores $${CORES:-2}

paper: scratchdir
	@[ -f "$${PROFILE:-}" ] || (echo "usage: make paper PROFILE=configs/profiles/paper.yaml" && exit 1)
	snakemake -s src/compbench/pipeline/Snakefile \
	    --configfile "$$PROFILE" \
	    --cores $${CORES:-4} \
	    --keep-going \
	    $${SNAKEMAKE_ARGS:-}

# --keep-going: at 336-cell scale, one bad cell (T.261 timeout, OOM, …) should
# not block the report on the remaining 335. The aggregator is already
# tolerant of missing cells (rglob("metrics.json")).

full: scratchdir
	@[ -f "$${PROFILE:-}" ] || (echo "usage: make full PROFILE=configs/profiles/full.yaml" && exit 1)
	snakemake -s src/compbench/pipeline/Snakefile \
	    --configfile "$$PROFILE" \
	    --cores $${CORES:-8} \
	    --keep-going \
	    $${SNAKEMAKE_ARGS:-}

.PHONY: containers containers-apptainer
containers:
	./containers/build.sh
containers-apptainer:
	./containers/to_apptainer.sh compbench-base:$${TAG:-local}
	./containers/to_apptainer.sh compbench-ks25:$${TAG:-local}
	./containers/to_apptainer.sh compbench-ks4:$${TAG:-local}

.PHONY: clean
clean:
	rm -rf .venv .tox build dist *.egg-info results
