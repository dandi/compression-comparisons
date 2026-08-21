# REVIEW DRAFT — datalad PR #7901

*(Ready to post at https://github.com/datalad/datalad/pull/7901.
Reproducers: `.specify/specs/repro/datalad-pr7901-*.sh`.
Body below the line.)*

---

Tested at `db1e0ef3b` against the two cases I filed (#7899, #7900) plus the
combinations they compose into. **Both reported defects are fixed**, and the
fixes hold well under the parallelism I could throw at them. Two things
found: one regression, one stated property that does not hold.

Environment: datalad `1.6.2+10.gdb1e0ef3b` in a venv, git 2.47.3,
git-annex 10.20260717, Debian 13, local btrfs, 32 cores. Comparison runs use
stock datalad 1.6.2.

## What works

**#7899, flat concurrency — fixed, and it scales.** N concurrent
`run --explicit`, each declaring one output, checking not just the record
count but that every run commit contains *exactly* its declared output:

| N | records | mismatched commits | untracked | merges |
| -: | -: | -: | -: | -: |
| 8 | 8/8 | 0 | 0 | 0 |
| 16 | 16/16 | 0 | 0 | 0 |
| 32 | 32/32 | 0 | 0 | 0 |
| 64 | 64/64 | 0 | 0 | 0 |

No `index.lock` failures at any level (was 4/6 trials at N=8 before).

**#7900, nesting — fixed.** Variant B of my reproducer (outer declares only
its own output) now exits 0 with all three records and a clean tree, with no
configuration override.

**The shape I actually needed — one outer run, N inner runs in parallel —
works.** This is the case my benchmark is built on, and it is the one I was
most worried about, since it is nesting and concurrency at once. Clean at
N=4/8/16 on a text2git dataset, and at N=16×4 MB and N=32×8 MB of binary
payload on an annexed dataset: one outer record, N inner records, every
inner commit containing exactly its own output, nothing untracked.

**The input check behaves as documented,** with no false positives in the
cases most likely to produce them: a clean input runs; a modified declared
input is `impossible`; an untracked file merely *inside* a declared
directory input does not trip it; a dirty file that is not a declared input
does not trip it; `--assume-ready=inputs` overrides. `datalad.run.dirty-inputs`
works as described.

**Tests pass locally**: `test_run.py` 37 passed, `test_rerun.py` 22 passed +
1 xfailed, `test_save.py` 45 passed + 3 skipped + 1 xfailed.

## 1. Regression: a run whose output is in a subdataset, concurrent with a run in that subdataset

`repro/datalad-pr7901-subdataset-concurrent.sh`

A `run --explicit` in a superdataset declaring `--output sub/a1`, concurrent
with a `run --explicit` inside `sub`. This works on stock datalad and breaks
here:

| | both runs succeed |
| --- | -: |
| stock 1.6.2 | **8/8** |
| PR #7901 | **4/8** |

In the failing trials one run exits non-zero, produces no record, and
**leaves its declared output untracked** — so the dataset is left with a
file the run was supposed to commit and no provenance for it. Two error
forms appear:

```
fatal: Unable to create '.../ds/sub/.git/index.lock': File exists.
error: pathspec 'a1' did not match any file(s) known to git
```

The lock looks like the cause. `_lock_save()` locks
`ds.repo.dot_git/datalad/run-save.lck` — the dataset the run was *invoked*
in. But `Save.__call__(..., recursive=True)` writes to the subdataset's
index as well. The superdataset run holds `ds/.git/…/run-save.lck` while
writing `ds/sub/.git/index`; the subdataset run holds
`ds/sub/.git/…/run-save.lck`. Different locks, same index — so the
serialization that fixes the flat case does not cover this one.

The second error form is the new part. With `_partial_commit` the commit
carries a pathspec, and a pathspec commit needs its paths staged or tracked;
when the concurrent save consumes the staged entry, `commit -- a1` now
hard-fails where the pathspec-less commit used to succeed. So the pathspec
change turns a previously-won race into a hard failure. That is arguably the
more honest outcome, but the run should not exit leaving a declared output
uncommitted.

Locking every repository the save will touch — or at minimum the
superdataset lock being taken by subdataset runs too — would close it.

## 2. "Only a run's own commits are wrapped in its merge" does not hold for concurrent *outer* runs

`repro/datalad-pr7901-nested-concurrent.sh`

Two concurrent outer runs, each performing inner runs. All records are
created and the tree is clean, but the merge topology is wrong:

```
*   be79860 | [DATALAD RUNCMD] sweep 2
|\
| * e98d7ad | Remaining changes after command execution
| * cb660ec | [DATALAD RUNCMD] sweep 1     <- merge, second parent below
|/|
| * 7e4b3a2 | Remaining changes after command execution
| * a5b67dc | [DATALAD RUNCMD] cell 2.2    <- sweep 2's cell,
| * 5bf13c0 | [DATALAD RUNCMD] cell 1.2       on sweep 1's merge
| * 99a870a | [DATALAD RUNCMD] cell 2.1
| * fb3bbc8 | [DATALAD RUNCMD] cell 1.1
```

Sweep 1's merge subsumes sweep 2's cell commits. Deterministic: 5/5 trials
at N=2, 2 cross-wrapping merges per trial; 20 at N=4, 80 at N=8.

This has a concrete consequence — `datalad rerun` of sweep 1's record
re-executes the other sweep's commands and re-materialises its files:

```
$ datalad rerun --explicit d5384c8      # sweep 1
unlock(ok): o_1_1 (file)
unlock(ok): o_1_2 (file)
unlock(ok): o_2_1 (file)      <- sweep 2's outputs
unlock(ok): o_2_2 (file)
run (ok: 6)
```

which is the failure mode #7899 was filed about, one level up.

**To be fair to the PR: this is pre-existing, not introduced.** Stock
datalad cross-wraps too, when it manages to produce the records at all
(it usually loses them first). But it is the property the third measure
claims — *"Only a run's own commits are wrapped into its merge commit …
Without this, a concurrent run's record would end up on the second parent of
an unrelated run's merge"* — and by making nested+concurrent runs succeed,
the PR makes the residual misattribution reliably reachable where it was
previously masked by the record loss.

The reason is that `_has_own_commits()` gates only the *boolean*:

```python
cmd_made_commits = (... and _has_own_commits(ds.repo, pre_cmd_hexsha, post_cmd_hexsha, run_token))
...
since=pre_cmd_hexsha if cmd_made_commits else None,
```

The ancestry token correctly identifies *whether* this run committed, but
the merge range stays `pre_cmd_hexsha..HEAD`, which spans the sibling's
commits. And when foreign commits are interleaved on one linear chain, no
single second parent can cover only your own — so narrowing the range is not
enough. Options as I see them: fall back to a plain commit of the declared
outputs when the range contains run commits belonging to another run (the
ancestry token already tells you), or state it as a limitation. Either is
fine by me; silently producing a merge that `rerun` acts on is the part
worth avoiding.

## Minor

- `_lock_save()` reimplements what `datalad.support.locking` already
  offers. `try_lock_informatively()` would report *which* PID holds the
  lock and supports timeouts, where the current `acquire()` blocks
  indefinitely with a single info message. Not a correctness issue —
  `InterProcessLock` is fcntl-based, so a dead holder releases — but the
  diagnostics are nicer and it is one code path instead of two.
- `_execute_command()` now always passes an explicit `env`, where it
  previously passed `None` and inherited. Worth confirming that
  `WitlessRunner` treats an explicit copy of `os.environ` identically to
  inheriting it.
- `DATALAD_RUN_ANCESTRY` is exported into the command's environment and
  will be inherited by anything the command leaves running.
- Targeting: the input check is a behaviour change that turns
  previously-working calls into `impossible`, and it comes with a new
  configuration variable. On a `maint` branch that is a lot; I have no
  strong preference, but you asked in the description — I would put it on
  `master`. The #7899/#7900 fixes are true bugfixes and could go to `maint`
  on their own.

## Summary

The two defects I reported are genuinely fixed and hold at 64-way
parallelism, and the case my own work depends on — one outer run with many
parallel inner runs — is solid, including with annexed binary payloads.
Finding 1 is a real regression in a case that works today and I would want
it addressed before merge. Finding 2 is pre-existing and I would be content
with it documented as a limitation, as long as it is not described as fixed.

Thanks for taking these on so quickly — the design document in particular
makes it much easier to review the reasoning rather than just the diff.
