#!/bin/bash
set -uo pipefail
TOOL=/data/yoh/compression-comparisons
STUDY=$TOOL/results/dandi-t261-compression-study
export PATH="$TOOL/vendor/wavpack/bin:$TOOL/.venv/bin:$PATH"
export LD_LIBRARY_PATH="$TOOL/vendor/wavpack/lib:${LD_LIBRARY_PATH:-}"
export BWC_CFG_DIR=$TOOL/configs/bwc-cfg TMPDIR=$STUDY/.tmp COMPBENCH_BLOSC_THREADS=1
echo "waiting for the sorting run to finish..."
until grep -q 'ALL-DONE' "$TOOL/results/rung0-sorting.log" 2>/dev/null; do sleep 300; done
echo "=== Fig 14 waveform errors starting $(date -Is) ==="
"$TOOL/.venv/bin/python" "$TOOL/results/r0-waveform.py"
echo "=== WAVEFORM-DONE $(date -Is) ==="
