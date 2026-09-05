#!/bin/bash
# Do the Rung 0 profile survivors change SPIKE SORTING?
#
# Only 4 arms: r0-h8-fast and r0-h3-intra at QP 3.0 and 5.0. The reference
# (stock preset at the same QPs), the lossless null control and the
# bit-truncation positive control already exist, sorted, at 600 s in
# derivatives/sorting-2026-08-26-sorting-eval-t261-600s -- and r0-stock.cfg
# is byte-identical to combinedPresetEEG_IndepChannel, so those arms ARE the
# matched reference. Every parameter below matches that run exactly
# (600 s, lsb 12, chunk 1.0 s, same MEArec file); the only code change since
# the study's pinned tool commit is report/aggregate.py, which is not on the
# compression path.
#
# NO DATALAD: writes outside the study dataset. The reproduction sweep is in
# flight, and run_sorting_sweep.sh would make 3 commits per arm inside its
# in-flight windows -- the failure mode that has already cost 14 cells
# (CLAUDE.md rule 2). Provenance gets recorded properly once the sweep drains.
set -uo pipefail
STUDY=/data/yoh/compression-comparisons/results/dandi-t261-compression-study
TOOL=/data/yoh/compression-comparisons
OUT=/data/yoh/compression-comparisons/results/rung0-sorting-600s
MEAREC=$STUDY/sourcedata/aind-ephys-compression/mearec/mearec_NP1.h5
DUR=600; LSB=12; CHUNK=1.0

WV=$TOOL/vendor/wavpack
export PATH="$WV/bin:$TOOL/.venv/bin:$PATH" LD_LIBRARY_PATH="$WV/lib:${LD_LIBRARY_PATH:-}"
export BWC_CFG_DIR=$TOOL/configs/bwc-cfg
export TMPDIR=$STUDY/.tmp                 # big partition, not the root overlay
export COMPBENCH_BLOSC_THREADS=1
mkdir -p "$OUT" "$TMPDIR"

compress_one() {   # preset qp
    local cell="$OUT/$1-qp$2"
    [ -f "$cell/compressed.zarr/.zgroup" ] && { echo "compress $1@$2: done"; return; }
    mkdir -p "$cell"
    compbench compress --mearec "$MEAREC" --lsb $LSB --duration-s $DUR \
        --codec t261 --codec-params "preset=$1,step_size_for_qp=$2" \
        --chunk-duration-s $CHUNK --output-dir "$cell" \
        > "$cell/compress.log" 2>&1 \
      && echo "compress $1@$2: $(tail -1 "$cell/compress.log")" \
      || echo "compress $1@$2: FAILED rc=$? -- $(tail -2 "$cell/compress.log" | tr '\n' ' ')"
}

# T.261 is single-threaded; run all four concurrently.
for p in r0-h8-fast r0-h3-intra; do for q in 3.0 5.0; do compress_one $p $q & done; done
wait
echo "=== compression stage complete $(date -Is) ==="

# Kilosort4 needs the GPU: strictly sequential.
for p in r0-h8-fast r0-h3-intra; do for q in 3.0 5.0; do
    cell="$OUT/$p-qp$q"
    [ -f "$cell/compressed.zarr/.zgroup" ] || { echo "sort $p@$q: SKIP (no zarr)"; continue; }
    if [ -d "$cell/sorting" ]; then echo "sort $p@$q: done"; else
        compbench spikesort --zarr "$cell/compressed.zarr" --output-dir "$cell" \
            > "$cell/sort.log" 2>&1 \
          && echo "sort $p@$q: ok" || echo "sort $p@$q: FAILED -- $(tail -2 "$cell/sort.log" | tr '\n' ' ')"
    fi
    if [ -f "$cell/sorting-metrics.json" ]; then echo "cmp $p@$q: done"; else
        compbench compare-sorting --sorting "$cell/sorting" --mearec "$MEAREC" \
            --duration-s $DUR --output-dir "$cell" > "$cell/cmp.log" 2>&1 \
          && echo "cmp $p@$q: ok" || echo "cmp $p@$q: FAILED -- $(tail -2 "$cell/cmp.log" | tr '\n' ' ')"
    fi
done; done
echo "=== ALL-DONE $(date -Is) ==="
