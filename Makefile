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

.DEFAULT_GOAL := help

.PHONY: help
help:
	@echo "Targets:"
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
integration:
	tox -e integration

.PHONY: smoke
smoke:
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

.PHONY: paper full snakemake-smoke
snakemake-smoke:
	snakemake -s src/compbench/pipeline/Snakefile \
	    --configfile configs/profiles/smoke.yaml \
	    --config results_dir=results/smoke-snakemake \
	    --cores $${CORES:-2}

paper:
	@[ -f "$${PROFILE:-}" ] || (echo "usage: make paper PROFILE=configs/profiles/paper.yaml" && exit 1)
	snakemake -s src/compbench/pipeline/Snakefile \
	    --configfile "$$PROFILE" \
	    --cores $${CORES:-4} \
	    $${SNAKEMAKE_ARGS:-}

full:
	@[ -f "$${PROFILE:-}" ] || (echo "usage: make full PROFILE=configs/profiles/full.yaml" && exit 1)
	snakemake -s src/compbench/pipeline/Snakefile \
	    --configfile "$$PROFILE" \
	    --cores $${CORES:-8} \
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
