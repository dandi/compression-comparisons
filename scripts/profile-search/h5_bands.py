"""H5 judged in the band the sorter actually uses.

Total rmse is the wrong metric for a band-split codec by construction: the
whole point is to spend error below 300 Hz, which spike sorting discards. The
sorter-relevant number is rmse inside 300-6000 Hz. The LFP-band number is
reported too, because that is what is being sacrificed and the study cares
about LFP as a separate use case.
"""
import numpy as np, time
from pathlib import Path
from scipy.signal import butter, sosfiltfilt
from compbench.datasets.aind_benchmark import load_aind_benchmark
from compbench.codecs.t261 import T261Codec
from compbench.codecs.t261_bandsplit import T261BandSplitCodec

S = Path("results/dandi-t261-compression-study/sourcedata/aind-ephys-compression")
d = load_aind_benchmark(path=S/"ibl-np1/CSHZAD026_2020-09-04_probe00",
                        start_s=0.0, duration_s=10.0)
x = np.ascontiguousarray(np.asarray(d.data if hasattr(d,"data") else d[0]))
fs = float(d.sample_rate_hz)
xf = x.astype(np.float64)
sd = xf.std()

sos_sp = butter(4, [300.0, 6000.0], btype="band", fs=fs, output="sos")
sos_lf = butter(4, 300.0, btype="low", fs=fs, output="sos")
def band_rmse(err, sos):
    return float(np.sqrt((sosfiltfilt(sos, err, axis=0) ** 2).mean()))

print(f"input {x.shape} fs={fs} sigma={sd:.3f}\n", flush=True)
print(f"  {'arm':26} {'CR':>7} {'total':>8} {'SPIKE 300-6k':>13} {'LFP <300':>9} "
      f"{'>5sig':>8} {'enc_s':>7}", flush=True)

def run(label, codec):
    t0 = time.time(); enc = bytes(codec.encode(x)); t = time.time()-t0
    dec = np.asarray(codec.decode(enc)).reshape(x.shape).astype(np.float64)
    e = dec - xf
    hi = np.abs(xf) > 5*sd
    print(f"  {label:26} {x.nbytes/len(enc):7.4f} {np.sqrt((e**2).mean()):8.4f} "
          f"{band_rmse(e, sos_sp):13.4f} {band_rmse(e, sos_lf):9.4f} "
          f"{np.sqrt((e[hi]**2).mean()):8.4f} {t:7.1f}", flush=True)

run("plain t261 qp=5 (ref)", T261Codec(preset="r0-stock", step_size_for_qp=5.0))
for qp_lo in (5.0, 20.0, 40.0):
    run(f"bandsplit qp_lo={qp_lo:<4} hi=5",
        T261BandSplitCodec(sample_rate_hz=fs, qp_lo=qp_lo, qp_hi=5.0))
