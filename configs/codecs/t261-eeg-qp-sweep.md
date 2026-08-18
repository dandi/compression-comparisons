# T.261 EEG lossy QP sweep — quality-vs-CR analogue of WavPack-Hybrid

The `combinedPresetEEG_IndepChannel_lossless` preset (StepSizeForQP=1.0) is
lossless. The stock lossy preset `combinedPresetEEG_IndepChannel` uses
StepSizeForQP=1.001 (barely-lossy). To sweep quality similarly to how the
Buccino et al. 2023 paper swept WavPack-Hybrid's `bps=2.25..6`, override
`StepSizeForQP` at codec-instantiation time. Each YAML below is one point
on the CR-vs-distortion Pareto plot.

Rule of thumb (subject to empirical verification on real data):

| Config file                | StepSizeForQP | Expected mode                    |
| -------------------------- | ------------- | -------------------------------- |
| t261-eeg-qp1.5.yaml        | 1.5           | very high fidelity, small CR gain |
| t261-eeg-qp2.yaml          | 2.0           | high fidelity                    |
| t261-eeg-qp3.yaml          | 3.0           | medium fidelity                  |
| t261-eeg-qp5.yaml          | 5.0           | aggressive                       |
| t261-eeg-qp8.yaml          | 8.0           | very aggressive                  |

Distortion (PRD, PRDN, RMSE-band-filtered) and CR must be measured on the
target dataset — the T.261 spec does not fix the CR/distortion relationship
across signals with different statistics.

For ephys (30 kHz Neuropixels), the analogous knob targeting bit-per-sample
comparability with WavPack-Hybrid should be tuned empirically once we have
paper-comparable data — a candidate first sweep is the same StepSizeForQP
range above, and comparing PRDN + WavPack-Hybrid RMSE_bp side by side.
