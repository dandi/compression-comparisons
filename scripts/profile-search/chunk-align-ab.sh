#!/bin/bash
# Chunk-alignment A/B: does the ragged-block defect inflate false positives?
#
# THE DEFECT. Every T.261 cell in this study encodes 1 s chunks at
# LOG2_MAX_BLOCK_SIZE 10. 32000 % 1024 = 256, so each chunk ends in a
# remainder block that BWC extends by REPLICATING the last sample. That DC
# step makes the final block code at 2.46x the body's rmse, peaking at 3.6x
# QP, on 209/384 channels -- ~600 bursts per 600 s recording. Measured and
# verified twice; mirror-padding or chunk alignment removes it entirely.
#
# THE QUESTION. A periodic burst of 3.6x QP errors on half the channels is a
# plausible false-positive generator that aggregate in-band rmse cannot see.
# It is a candidate answer to the study's standing puzzle: T.261 carries ~2x
# LOWER in-band error than WavPack yet produces +19 FP against WavPack's +5.
# It is also asymmetric -- T.261-specific -- so the headline comparison may be
# measuring a fixable defect rather than the codec's intrinsic behaviour.
#
# THE DESIGN. Two arms differing in ONE parameter:
#   A  chunk 1.000 s = 32000 samples -> 256 left over a 1024 block (defect)
#   B  chunk 1.024 s = 32768 samples -> 0 left over (no remainder, no padding,
#      no rate cost). 32000 x 1.024 = 32768 = 32 x 1024 exactly; the same
#      trick works at 30 kHz (30720 = 30 x 1024).
#
# Arm A is re-run rather than reused from the Aug 26 reference, even though
# the compression path is unchanged at the new pin, so that reproducing its
# FP of 145 doubles as a check that the re-pin changed nothing.
#
# READ FP, NOT well_detected. Across the 600 s QP ladder FP is monotone in
# distortion (129/133/138/145/184) while well_detected scatters
# non-monotonically (94/98/98/96/99) and is HIGHER at QP 8.0 than QP 5.0. So
# +-2 well-detected units is noise and cannot carry the conclusion.
# Lossless anchor: 96 well-detected / 126 FP / 23 redundant / 0.9809 accuracy.
#
# NO DATALAD: writes outside the study dataset, so it cannot collide with a
# sweep. Provenance is recorded afterwards.
set -uo pipefail
STUDY=/data/yoh/compression-comparisons/results/dandi-t261-compression-study
TOOL=/data/yoh/compression-comparisons
OUT=$TOOL/results/chunk-align-ab
MEAREC=$STUDY/sourcedata/aind-ephys-compression/mearec/mearec_NP1.h5
DUR=600; LSB=12; QP=5.0

WV=$TOOL/vendor/wavpack
export PATH="$WV/bin:$STUDY/envs/compbench/bin:$PATH"
export LD_LIBRARY_PATH="$WV/lib:${LD_LIBRARY_PATH:-}"
export BWC_CFG_DIR=$TOOL/configs/bwc-cfg
export TMPDIR=$STUDY/.tmp COMPBENCH_BLOSC_THREADS=1
mkdir -p "$OUT" "$TMPDIR"

compress_one() {   # label chunk
    local cell="$OUT/$1"
    [ -f "$cell/compressed.zarr/.zgroup" ] && { echo "compress $1: done"; return; }
    mkdir -p "$cell"
    compbench compress --mearec "$MEAREC" --lsb $LSB --duration-s $DUR \
        --codec t261 --codec-params "preset=r0-stock,step_size_for_qp=$QP" \
        --chunk-duration-s "$2" --output-dir "$cell" > "$cell/compress.log" 2>&1 \
      && echo "compress $1: $(tail -1 "$cell/compress.log")" \
      || echo "compress $1: FAILED -- $(tail -2 "$cell/compress.log" | tr '\n' ' ')"
}

echo "=== chunk-alignment A/B starting $(date -Is) ==="
compress_one chunk1.000 1.0 &
compress_one chunk1.024 1.024 &
wait
echo "=== compression done $(date -Is); sorting (GPU, serial) ==="

for arm in chunk1.000 chunk1.024; do
    cell="$OUT/$arm"
    [ -f "$cell/compressed.zarr/.zgroup" ] || { echo "sort $arm: SKIP (no zarr)"; continue; }
    if [ -d "$cell/sorting" ]; then echo "sort $arm: done"; else
        compbench spikesort --zarr "$cell/compressed.zarr" --output-dir "$cell" \
            > "$cell/sort.log" 2>&1 && echo "sort $arm: ok" \
          || echo "sort $arm: FAILED -- $(tail -2 "$cell/sort.log" | tr '\n' ' ')"
    fi
    if [ -f "$cell/sorting-metrics.json" ]; then echo "cmp $arm: done"; else
        compbench compare-sorting --sorting "$cell/sorting" --mearec "$MEAREC" \
            --duration-s $DUR --output-dir "$cell" > "$cell/cmp.log" 2>&1 \
          && echo "cmp $arm: ok" || echo "cmp $arm: FAILED -- $(tail -2 "$cell/cmp.log" | tr '\n' ' ')"
    fi
done
echo "=== AB-DONE $(date -Is) ==="
