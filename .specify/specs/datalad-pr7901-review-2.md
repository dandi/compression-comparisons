# REVIEW BUNDLE (round 2) — datalad PR #7901 at `031ef044`

*(Single self-contained bundle. Everything below the `---` is the postable
body. Post with `sh post-pr7901-review.sh --bundle datalad-pr7901-review-2.md --post`.)*

---

> **Who wrote this.** Follow-up review by **Claude Code** (v2.1.239, model
> `claude-opus-5`) running on the reporter's machine, posted from their
> account rather than written by them. Every number below is from an actual
> run against `031ef044`; the reproducers are the same ones embedded in the
> previous review, re-run unchanged, plus one new stress script embedded
> here.

Re-tested at `031ef044`. **Both findings are fixed**, verified with the same
scripts that produced the original numbers, and nothing that passed before
regressed. Same environment as before: datalad `1.6.2+11.g031ef0443` in a
venv, git 2.47.3, git-annex 10.20260717, Debian 13, local btrfs, 32 cores.

## Finding 1 — fixed

Superdataset run with an output inside a subdataset, concurrent with a run
in that subdataset (`PR7901-SUBDS`, unchanged):

| | both runs succeed |
| --- | -: |
| stock 1.6.2 | 8/8 |
| PR at `db1e0ef3b` | 4/8 |
| **PR at `031ef044`** | **8/8** |

No `index.lock` failures, no `pathspec … did not match`, nothing left
untracked.

Pushing harder than the filed reproducer did — N runs in the superdataset
each writing into a subdataset, concurrent with N runs inside each of *two*
subdatasets, so all three levels contend for the one lock
(`PR7901-HIER-STRESS`, new): **18 concurrent runs, 0 non-zero exits, 6/6
records at every level, nothing untracked, no errors** — twice, and again at
N=4.

Taking the lock on the topmost superdataset is the right shape for this, and
routing it through `try_lock_informatively()` is a bonus: the previous
`acquire()` would have stalled silently.

## Finding 2 — fixed

Concurrent outer runs, each performing inner runs
(`PR7901-NESTED-CONC`, unchanged): **0 cross-wrapping merges** in 5/5 trials
at N=2, and at N=4 and N=8 — previously 2, 20 and 80 respectively. The
history is now linear, with every record intact:

```
* d1dd806 [DATALAD RUNCMD] sweep 2
* 7650bbb [DATALAD RUNCMD] sweep 1
* 58d61c9 [DATALAD RUNCMD] cell 2.2
* 9362db9 [DATALAD RUNCMD] cell 1.2
* 71c6de0 [DATALAD RUNCMD] cell 2.1
* 5b5bd61 [DATALAD RUNCMD] cell 1.1
```

The consequence that made this worth reporting is gone. `rerun` of sweep 1
now re-executes sweep 1 only:

```
$ datalad rerun --explicit 7650bbb          # sweep 1
run(ok): [python3 -c "open('o_1_1','w').write('x')...]
unlock(ok): o_1_2 (file)
run(ok): [python3 -c "open('o_1_2','w').write('x')...]
run(ok): [./sweep.sh 1]
  run (ok: 1)
```

against `unlock(ok): o_2_1`, `o_2_2` and `run (ok: 6)` before.

Dropping the merge rather than trying to narrow its range is the right call —
the reasoning in the design document (a merge has one second parent, so no
range covers only this command once commits interleave) is exactly why
narrowing cannot work, and the cost is stated plainly where someone will
find it.

## No regressions

Everything that passed in the previous round still passes at `031ef044`:

| check | result |
| --- | --- |
| `PR7901-FLAT` N=8 / 32 / 64 | 8/8, 32/32, 64/64 records, 0 mismatched, 0 untracked |
| `PR7901-OUTER` N=8 / 16 | 1 outer + N inner, 0 mismatched, 0 untracked |
| `PR7901-ANNEX` N=16 × 4 MB | clean |
| `PR7901-INPUTS` | 4 × `run(ok)`, 1 × `run(impossible)`, as documented |

Test suites: `test_run.py` **39 passed** (up from 37 — one new test per
finding), `test_rerun.py` 22 passed + 1 xfailed, `test_save.py` 45 passed +
3 skipped + 1 xfailed.

## Two small notes, neither blocking

**`_lock_save()` discards the value `try_lock_informatively()` yields.** The
context manager yields `True` when it holds the lock and `False` when it
gave up and proceeded unlocked, and the caller ignores it. Proceeding
unlocked is precisely the condition under which gh-7899's silent
misattribution can reappear, so it seems worth a `lgr.warning` from
`_lock_save` rather than leaving it at the `INFO`-level "Will proceed
without locking" from inside the helper. That message *is* visible at
datalad's default level, so this is about severity rather than visibility —
but a run that continues in exactly the unprotected mode this PR exists to
remove reads like a warning, not information. Reaching it takes ~41 minutes
of contention (`5+60+600+1800`), so it should be rare.

**The lock now spans the whole hierarchy.** Two `run`s in unrelated
subdatasets of a large superdataset serialize their saving phases even
though they never touch a shared index. That is the correct trade for
correctness and the saving phase is short, but it is a behaviour worth
knowing about for a wide hierarchy driven by many parallel runs. No action
suggested — just noting it is a consequence, not an oversight.

## Summary

Both findings verified fixed, with a regression test apiece, no regressions
elsewhere, and the hierarchy lock holding under 18-way concurrency across
three datasets. From the perspective of the two issues this PR closes, and
of the parallel-sweep use case that produced them, this looks ready.

## Reproducers

The five referenced above are embedded unchanged in the previous review
comment. The one new script is below. POSIX `sh`, `mktemp -d`, directory
left behind for inspection; run with the `datalad` under test first on
`PATH`.

<details>
<summary><b>PR7901-HIER-STRESS</b> — <code>datalad-pr7901-hierarchy-stress.sh</code> — N super runs writing into a subdataset, concurrent with N runs in each of two subdatasets</summary>

```sh
#!/bin/sh
# Check (datalad PR #7901 review, round 2): heavier than the filed
# reproducer for finding 1 -- N runs in a superdataset, each declaring an
# output inside a subdataset, concurrent with N runs inside each of two
# subdatasets. All three levels contend for the topmost-superdataset lock.
#
# Usage: sh datalad-pr7901-hierarchy-stress.sh [N]
#
# The temp directory is deliberately left behind for inspection.

set -eu

N="${1:-6}"
D="$(mktemp -d "${TMPDIR:-/tmp}/dl-pr7901-hier-XXXXXXX")"
datalad create -c text2git "$D/ds" >/dev/null 2>&1
datalad create -c text2git -d "$D/ds" "$D/ds/subA" >/dev/null 2>&1
datalad create -c text2git -d "$D/ds" "$D/ds/subB" >/dev/null 2>&1
cd "$D/ds"

i=1
while [ "$i" -le "$N" ]; do
    ( datalad run --explicit --output "subA/s$i" -m "super $i" \
        "python3 -c \"open('subA/s$i','w').write('x')\"" >>"$D/log" 2>&1
      echo "super=$?" >>"$D/rc" ) &
    ( cd "$D/ds/subA" && datalad run --explicit --output "a$i" -m "subA $i" \
        "python3 -c \"open('a$i','w').write('x')\"" >>"$D/log" 2>&1
      echo "subA=$?" >>"$D/rc" ) &
    ( cd "$D/ds/subB" && datalad run --explicit --output "b$i" -m "subB $i" \
        "python3 -c \"open('b$i','w').write('x')\"" >>"$D/log" 2>&1
      echo "subB=$?" >>"$D/rc" ) &
    i=$((i + 1))
done
wait || true

echo "runs=$((N * 3)) nonzero_exits=$(grep -cv '=0$' "$D/rc" || true)"
echo "  super records: $(git log --format=%s | grep -c 'RUNCMD] super' || true)/$N"
echo "  subA records:  $(git -C subA log --format=%s | grep -c 'RUNCMD] subA' || true)/$N"
echo "  subB records:  $(git -C subB log --format=%s | grep -c 'RUNCMD] subB' || true)/$N"
echo "  untracked: super=$(git status --porcelain | grep -c '^??' || true)" \
     "subA=$(git -C subA status --porcelain | grep -c '^??' || true)" \
     "subB=$(git -C subB status --porcelain | grep -c '^??' || true)"
echo "  index.lock / pathspec / run(error) occurrences: $(grep -c 'index.lock\|did not match\|run(error)' "$D/log" || true)"
echo "  ($D)"
```

</details>
