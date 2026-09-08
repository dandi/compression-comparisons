"""Fig 14 waveform-feature errors for the profile arms — the paper's own criterion.

Unit counts are the weaker endpoint: bittrunc bits=4 scores 100/100
well-detected (better than lossless) while nearly tripling FP, so a count can
rise while precision collapses. The paper judges on a waveform-feature
DISTRIBUTION against a 10 % line, and verdict() scores p90 rather than max —
scoring max once reported WavPack 2.25 bps as failing a result the paper
states explicitly.

Reads the stock reference cells from the study dataset; writes nothing there.
"""
import json, os, sys
from compbench.waveform_errors import waveform_errors_for_cell, verdict

R = "/data/yoh/compression-comparisons/results"
STUDY = f"{R}/dandi-t261-compression-study"
MEAREC = f"{STUDY}/sourcedata/aind-ephys-compression/mearec/mearec_NP1.h5"
D = f"{STUDY}/derivatives/sorting-2026-08-26-sorting-eval-t261-600s"

ARMS = [
    ("stock@QP3.0",   f"{D}/t261-68e11cda"),
    ("h8-fast@QP3.0", f"{R}/rung0-sorting-600s/r0-h8-fast-qp3.0"),
    ("h3-intra@QP3.0",f"{R}/rung0-sorting-600s/r0-h3-intra-qp3.0"),
    ("stock@QP5.0",   f"{D}/t261-2ab16306"),
    ("h8-fast@QP5.0", f"{R}/rung0-sorting-600s/r0-h8-fast-qp5.0"),
    ("h3-intra@QP5.0",f"{R}/rung0-sorting-600s/r0-h3-intra-qp5.0"),
]
MAX_UNITS = int(os.environ.get("MAX_UNITS", "0")) or None

out = {}
for label, cell in ARMS:
    if not os.path.isdir(os.path.join(cell, "compressed.zarr")):
        print(f"{label}: SKIP (no zarr)", flush=True); continue
    try:
        r = waveform_errors_for_cell(cell, MEAREC, lsb=12, max_units=MAX_UNITS)
        v = verdict(r)
        out[label] = {"result": r, "verdict": v}
        feats = sorted((r.get("summary") or {}).keys())
        p90 = {k: r["summary"][k]["p90_relative_error"] for k in feats}
        mx  = {k: r["summary"][k]["max_relative_error"] for k in feats}
        print(f"{label}: within_10pct={v.get('within_tolerance')} "
              f"worst={v.get('worst_feature')}@{v.get('worst_relative_error'):.4f} "
              f"cr={r.get('cr')}", flush=True)
        for k in feats:
            print(f"    {k:22} p90={p90[k]:.4f}  max={mx[k]:.4f}", flush=True)
    except Exception as e:
        print(f"{label}: ERROR {type(e).__name__}: {e}", flush=True)

with open(f"{R}/r0-waveform-results.json", "w") as f:
    json.dump(out, f, indent=2, default=str)

# side-by-side p90, the number that decides
if out:
    feats = sorted({k for v in out.values() for k in (v["result"].get("summary") or {})})
    w = max(len(f) for f in feats) if feats else 10
    print("\np90 relative error (paper's line = 0.10):", flush=True)
    hdr = f"  {'feature':{w}} " + " ".join(f"{l:>16}" for l, _ in ARMS if l in out)
    print(hdr); print("  " + "-"*(len(hdr)-2))
    for k in feats:
        cells = []
        for l, _ in ARMS:
            if l not in out: continue
            s = (out[l]["result"].get("summary") or {}).get(k)
            cells.append(f"{s['p90_relative_error']:16.4f}" if s else f"{'--':>16}")
        print(f"  {k:{w}} " + " ".join(cells))
