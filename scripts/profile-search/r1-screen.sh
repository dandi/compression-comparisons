#!/bin/bash
# H6 / H7 screen -- the hypotheses that change WHERE the error goes.
#
# Rung 0 screened on CR and cost. Both turned out flat across candidates, and
# neither says anything about spike sorting. H6 (per-channel distortion
# scaling) and H7 (error structure: quantiser mode, trellis, perceptual) are
# specifically about the error's DISTRIBUTION at fixed magnitude, so this
# screen measures distribution:
#
#   * per-channel rmse/sigma spread -- H6's direct target. Stock scales
#     distortion uniformly (ChannelDistortionScaleFactor 0.0), so channels
#     whose sigma is small get the worst error-to-noise. Kilosort thresholds
#     per channel on k*MAD, so that spread is what should matter. H6 should
#     COMPRESS this spread.
#   * amplitude-stratified rmse -- spike-band fidelity, the proxy validated
#     against H8 (differences there were 7.4x enriched on |x|>5 sigma).
#   * CR and cost -- a candidate that wins on distribution but drops below
#     CR 7.16 is still useless: that is WavPack Hybrid's rate ceiling and
#     T.261's only defensible territory (plan, "do not pursue").
#
# QP 5.0, on MEArec NP1 with lsb=12 -- matching the substrate and
# preprocessing of the 600 s sorting runs these feed into.
#
# WAITS for the profile sorting run's compression stage so the two do not
# contend for CPU; that run moves to GPU afterwards, leaving cores free.
set -uo pipefail
TOOL=/data/yoh/compression-comparisons
STUDY=$TOOL/results/dandi-t261-compression-study
OUT=$TOOL/results/r1-screen
MEAREC=$STUDY/sourcedata/aind-ephys-compression/mearec/mearec_NP1.h5
QP=5.0; DUR=10; LSB=12

WV=$TOOL/vendor/wavpack
export PATH="$WV/bin:$TOOL/.venv/bin:$PATH" LD_LIBRARY_PATH="$WV/lib:${LD_LIBRARY_PATH:-}"
export BWC_CFG_DIR=$TOOL/configs/bwc-cfg
export TMPDIR=$STUDY/.tmp
export COMPBENCH_BLOSC_THREADS=1
mkdir -p "$OUT"

echo "waiting for the sorting run's compression stage..."
until grep -q 'compression stage complete' "$TOOL/results/rung0-sorting.log" 2>/dev/null; do sleep 120; done
echo "=== r1 screen starting $(date -Is) ==="

for cand in r0-stock r1-h6-ctrl r1-h6-cds05 r1-h6-cds10 \
            r1-h7-quant0 r1-h7-quant2 r1-h7-trellis r1-h7-percept; do
  (
    cell="$OUT/$cand"
    if [ ! -f "$cell/compressed.zarr/.zgroup" ]; then
      mkdir -p "$cell"
      /usr/bin/time -f %e -o "$cell/wall.txt" \
        compbench compress --mearec "$MEAREC" --lsb $LSB --duration-s $DUR \
          --codec t261 --codec-params "preset=$cand,step_size_for_qp=$QP" \
          --chunk-duration-s 1.0 --output-dir "$cell" > "$cell/log" 2>&1 \
        || echo "FAILED $cand: $(tail -2 "$cell/log" | tr '\n' ' ')"
    fi
  ) &
done
wait
echo "=== r1 screen compression done $(date -Is); analysing ==="
"$TOOL/.venv/bin/python" "$TOOL/results/r1-analyse.py" > "$OUT/REPORT.txt" 2>&1
cat "$OUT/REPORT.txt"
echo "=== R1-SCREEN-DONE $(date -Is) ==="
