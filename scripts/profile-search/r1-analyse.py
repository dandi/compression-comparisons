"""Analyse the H6/H7 screen: error DISTRIBUTION, not just magnitude."""
import json, glob, os
import numpy as np
import spikeinterface as si
from compbench.datasets.mearec import load_recording

OUT = "/data/yoh/compression-comparisons/results/r1-screen"
MEAREC = ("/data/yoh/compression-comparisons/results/dandi-t261-compression-study"
          "/sourcedata/aind-ephys-compression/mearec/mearec_NP1.h5")

rec, _ = load_recording(MEAREC, start_s=0.0, duration_s=10.0, lsb=12)
ref = np.asarray(rec.get_traces(segment_index=0)).astype(np.float64)
ch_sd = ref.std(axis=0)
ch_sd[ch_sd == 0] = np.nan
gsd = ref.std()
print(f"reference {ref.shape}, sigma={gsd:.3f}, per-channel sigma "
      f"min={np.nanmin(ch_sd):.2f} max={np.nanmax(ch_sd):.2f} "
      f"spread={np.nanmax(ch_sd)/np.nanmin(ch_sd):.1f}x\n")

rows = []
for cell in sorted(glob.glob(f"{OUT}/*/")):
    name = os.path.basename(cell.rstrip("/"))
    z = os.path.join(cell, "compressed.zarr")
    cm = os.path.join(cell, "compress-metrics.json")
    if not (os.path.exists(z) and os.path.exists(cm)):
        print(f"  {name}: MISSING"); continue
    m = json.load(open(cm))
    dec = np.asarray(si.read_zarr(z).get_traces(segment_index=0)).astype(np.float64)
    err = dec - ref
    per_ch = np.sqrt((err**2).mean(axis=0)) / ch_sd     # error-to-noise per channel
    wall = float(open(os.path.join(cell,"wall.txt")).read().strip()) if os.path.exists(os.path.join(cell,"wall.txt")) else float("nan")
    strat = {}
    for lbl, k in (("3s", 3), ("5s", 5)):
        msk = np.abs(ref) > k*gsd
        strat[lbl] = float(np.sqrt((err[msk]**2).mean())) if msk.any() else float("nan")
    rows.append(dict(name=name, cr=m["cr"], rmse=float(np.sqrt((err**2).mean())),
                     ch_med=float(np.nanmedian(per_ch)),
                     ch_iqr=float(np.nanpercentile(per_ch,75)-np.nanpercentile(per_ch,25)),
                     ch_spread=float(np.nanmax(per_ch)/np.nanmin(per_ch)),
                     e3=strat["3s"], e5=strat["5s"], wall=wall))

base = next((r for r in rows if r["name"] == "r0-stock"), None)
hdr = (f"{'candidate':16} {'CR':>7} {'cost':>6} {'rmse':>8} "
       f"{'err/sig med':>11} {'IQR':>8} {'max/min':>8} {'rmse>3sig':>9} {'rmse>5sig':>9}")
print(hdr); print("-"*len(hdr))
for r in sorted(rows, key=lambda r: -r["cr"]):
    cost = f"{r['wall']/base['wall']:.2f}x" if base and base["wall"] else "--"
    flag = "" if r["cr"] >= 7.16 else "  <7.16!"
    print(f"{r['name']:16} {r['cr']:7.3f} {cost:>6} {r['rmse']:8.4f} "
          f"{r['ch_med']:11.5f} {r['ch_iqr']:8.5f} {r['ch_spread']:8.2f} "
          f"{r['e3']:9.4f} {r['e5']:9.4f}{flag}")
if base:
    print(f"\nvs stock (ratios; <1 means the candidate COMPRESSES the spread):")
    for r in sorted(rows, key=lambda r: r["ch_iqr"]):
        if r["name"] == "r0-stock": continue
        print(f"  {r['name']:16} CR {r['cr']/base['cr']:6.4f}x  "
              f"err/sig-IQR {r['ch_iqr']/base['ch_iqr']:6.4f}x  "
              f"max/min {r['ch_spread']/base['ch_spread']:6.4f}x  "
              f"rmse>5sig {r['e5']/base['e5']:6.4f}x")
