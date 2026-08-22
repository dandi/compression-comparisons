# datalad pin — PR #7901

## The pin

```
datalad @ git+https://github.com/datalad/datalad.git@30b6deef70e6808de43c40bfe870462de7ae9373
```

reports itself as `datalad 1.6.2+13.g30b6deef7`. Install with:

```sh
uv tool install --force \
  "datalad @ git+https://github.com/datalad/datalad.git@30b6deef70e6808de43c40bfe870462de7ae9373"
```

## Why this is pinned rather than a release

Released datalad (<= 1.6.2) cannot give this study per-cell provenance.
Two defects make concurrent and nested `datalad run --explicit` unusable
for a parallel sweep, both filed from this work and both fixed only on
that branch:

- **gh-7899** — concurrent `run --explicit` in one dataset: one commit
  absorbs a sibling's outputs, the losing run exits 0 with **no run
  record**. Measured on 1.6.2: 12/12 trials lost a record at N=2,3,4,8.
- **gh-7900** — a nested `run` was rejected as an undeclared side effect
  unless the outer run redeclared every inner output, which for a
  runtime-determined cell list is not knowable when the outer command is
  built.

Plus two defects found reviewing the fix, also only on that branch: a
hierarchy-wide save lock (a superdataset run and a subdataset run were
racing one index under two locks), and a merge that wrapped a concurrent
run's commits, which made `datalad rerun` re-execute another run's
commands.

Verified at this commit, on this host: flat concurrency clean at N=64;
one outer run with 16 parallel inner runs clean, including 8 MB annexed
payloads; 18 concurrent runs across a superdataset and two subdatasets
clean; 0 cross-wrapping merges. Reproducers in `repro/`.

## Repin when it merges

This is a PR branch, not a release. Once #7901 merges, repin to the
released version that contains it and update:

- `results/dandi-t261-compression-study/code/run_sweep.sh` (guard)
- `results/dandi-t261-compression-study/code/run_sorting_loop.sh` (guard)
- `DEPLOY.md`
- this file

Do **not** repin while a sweep is in flight: the datalad producing the
records must not change mid-run, for the same reason the tool submodule
is pinned.
