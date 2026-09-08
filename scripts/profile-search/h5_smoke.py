"""End-to-end H5 check on real data: lossless must be exact, and the
band-split rate must be compared against plain T.261 at matched QP."""
import numpy as np, time
from pathlib import Path
from compbench.datasets.aind_benchmark import load_aind_benchmark
from compbench.codecs.t261 import T261Codec
from compbench.codecs.t261_bandsplit import T261BandSplitCodec, split_bands

S = Path("results/dandi-t261-compression-study/sourcedata/aind-ephys-compression")
d = load_aind_benchmark(path=S/"ibl-np1/CSHZAD026_2020-09-04_probe00",
                        start_s=0.0, duration_s=2.0)
x = np.ascontiguousarray(np.asarray(d.data if hasattr(d,"data") else d[0]))
fs = float(d.sample_rate_hz)
print(f"input {x.shape} fs={fs} nbytes={x.nbytes}", flush=True)

lo, hi = split_bands(x, fs, 300.0)
print(f"exact split: {np.array_equal(lo.astype(np.int32)+hi.astype(np.int32), x.astype(np.int32))}", flush=True)
print(f"  band std: lo={lo.std():.2f} hi={hi.std():.2f} full={x.std():.2f}", flush=True)

LOSSLESS = "combinedPresetEEG_IndepChannel_lossless"
def run(label, codec):
    t0 = time.time(); enc = bytes(codec.encode(x)); t = time.time()-t0
    dec = np.asarray(codec.decode(enc)).reshape(x.shape)
    err = dec.astype(np.float64) - x.astype(np.float64)
    print(f"  {label:34} cr={x.nbytes/len(enc):7.4f} rmse={np.sqrt((err**2).mean()):8.5f} "
          f"exact={np.array_equal(dec,x)} enc_s={t:6.1f}", flush=True)
    return x.nbytes/len(enc)

print("\nlossless null control (both bands lossless preset):", flush=True)
run("bandsplit lossless", T261BandSplitCodec(sample_rate_hz=fs, preset=LOSSLESS))
run("plain t261 lossless", T261Codec(preset=LOSSLESS))

print("\nmatched QP 5.0 on both bands vs plain t261 QP 5.0:", flush=True)
run("bandsplit qp_lo=5 qp_hi=5", T261BandSplitCodec(sample_rate_hz=fs, qp_lo=5.0, qp_hi=5.0))
run("plain t261 qp=5", T261Codec(preset="r0-stock", step_size_for_qp=5.0))

print("\nthe actual H5 question: coarsen the LFP band, hold the spike band", flush=True)
for qp_lo in (5.0, 10.0, 20.0, 40.0):
    run(f"bandsplit qp_lo={qp_lo:<4} qp_hi=5", 
        T261BandSplitCodec(sample_rate_hz=fs, qp_lo=qp_lo, qp_hi=5.0))
