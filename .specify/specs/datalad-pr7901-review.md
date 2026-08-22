# REVIEW BUNDLE — datalad PR #7901

*(Single self-contained bundle. Everything below the `---` is the postable
body, with all six reproducers embedded. Post with
`sh post-pr7901-review.sh --post`.)*

---

> **Who wrote this.** This review was produced by **Claude Code**
> (v2.1.239, model `claude-opus-5`) running on the reporter's machine, and
> is posted from their account rather than written by them. Every number
> below comes from an actual run against `db1e0ef3b`; each claim has an
> embedded reproducer, so nothing here needs to be taken on trust. Errors
> of judgement in it are the agent's.

Tested at `db1e0ef3b` against the two issues this PR closes (#7899, #7900)
plus the combinations they compose into. **Both reported defects are
fixed**, and the fixes hold under the parallelism available here. Two things
found: one regression, and one stated property that does not hold.

Environment: datalad `1.6.2+10.gdb1e0ef3b` installed in a fresh venv, git
2.47.3, git-annex 10.20260717, Python 3.13.5, Debian 13 (trixie), local
btrfs, 32 cores. Comparison rows labelled "stock" are datalad 1.6.2.

## What works

**#7899, flat concurrency — fixed, and it scales.** `PR7901-FLAT` checks
not merely that N run records exist, but that every run commit contains
*exactly* its declared output — a record count alone would not establish
that:

| N | records | mismatched commits | untracked | merges |
| -: | -: | -: | -: | -: |
| 8 | 8/8 | 0 | 0 | 0 |
| 16 | 16/16 | 0 | 0 | 0 |
| 32 | 32/32 | 0 | 0 | 0 |
| 64 | 64/64 | 0 | 0 | 0 |

No `index.lock` failures at any level; before the PR that was 4 of 6 trials
at N=8.

**#7900, nesting — fixed.** Variant B of the issue reproducer (outer run
declares only its own output) exits 0 with all three records and a clean
tree, with no configuration override.

**Nesting and concurrency together, in the shape that motivated the issues
— works.** One outer run whose command launches N inner runs in parallel is
what a sweep with per-cell provenance actually looks like, and it was the
case most likely to be left broken. `PR7901-OUTER` is clean at N=4/8/16:
one outer record, N inner records, every inner commit holding exactly its
own output, nothing untracked. `PR7901-ANNEX` repeats it on an annexed
dataset with binary payloads — N=16×4 MB and N=32×8 MB — also clean.

**The new input check behaves as documented,** with no false positives in
the cases most likely to produce them (`PR7901-INPUTS`): a clean input
runs; a modified declared input is `impossible`; an untracked file merely
*inside* a declared directory input does not trip it; a dirty file that is
not a declared input does not trip it; `--assume-ready=inputs` overrides.
`datalad.run.dirty-inputs` behaves as described.

**Test suites pass locally**: `datalad/core/local/tests/test_run.py` 37
passed; `datalad/local/tests/test_rerun.py` 22 passed, 1 xfailed;
`datalad/core/local/tests/test_save.py` 45 passed, 3 skipped, 1 xfailed.

## 1. Regression: a run whose output is in a subdataset, concurrent with a run in that subdataset

Reproducer `PR7901-SUBDS` below. A `run --explicit` in a superdataset
declaring `--output sub/a1`, concurrent with a `run --explicit` inside
`sub`. This works on stock datalad and breaks here:

| | both runs succeed |
| --- | -: |
| stock 1.6.2 | **8/8** |
| PR #7901 | **4/8** |

In the failing trials one run exits non-zero, produces no record, and
**leaves its declared output untracked** — the dataset is left holding a
file the run was meant to commit, with no provenance for it. Two error
forms appear:

```
fatal: Unable to create '.../ds/sub/.git/index.lock': File exists.
error: pathspec 'a1' did not match any file(s) known to git
```

The lock scope looks like the cause. `_lock_save()` locks
`ds.repo.dot_git/datalad/run-save.lck` — the dataset the run was *invoked*
in. But `Save.__call__(..., recursive=True)` writes the subdataset's index
too. The superdataset run holds `ds/.git/…/run-save.lck` while writing
`ds/sub/.git/index`; the subdataset run holds `ds/sub/.git/…/run-save.lck`.
Different locks, one index — so the serialization that fixes the flat case
does not cover this one.

The second error form is the new part. With `_partial_commit` the commit
carries a pathspec, and a pathspec commit needs its paths staged or
tracked; when the concurrent save consumes the staged entry, `commit -- a1`
hard-fails where the pathspec-less commit previously succeeded. So the
pathspec change converts a race that used to be won silently into a visible
failure. That is arguably the more honest outcome, but the run should not
exit leaving a declared output uncommitted.

Locking every repository the save will touch — or, more cheaply, having a
subdataset run also take its superdataset's lock — would close it.

## 2. "Only a run's own commits are wrapped in its merge" does not hold for concurrent *outer* runs

Reproducer `PR7901-NESTED-CONC` below. Two concurrent outer runs, each
performing inner runs. All records are created and the tree is clean, but
the merge topology is wrong:

```
*   be79860 | [DATALAD RUNCMD] sweep 2
|\
| * e98d7ad | Remaining changes after command execution
| * cb660ec | [DATALAD RUNCMD] sweep 1     <- merge; second parent below
|/|
| * 7e4b3a2 | Remaining changes after command execution
| * a5b67dc | [DATALAD RUNCMD] cell 2.2    <- sweep 2's cells, sitting
| * 5bf13c0 | [DATALAD RUNCMD] cell 1.2       on sweep 1's merge
| * 99a870a | [DATALAD RUNCMD] cell 2.1
| * fb3bbc8 | [DATALAD RUNCMD] cell 1.1
```

Sweep 1's merge subsumes sweep 2's cell commits. Deterministic: 5 of 5
trials at N=2, two cross-wrapping merges each; 20 at N=4; 80 at N=8.

The consequence is concrete — `datalad rerun` of sweep 1's record
re-executes the *other* sweep's commands and re-materialises its files:

```
$ datalad rerun --explicit d5384c8      # sweep 1
unlock(ok): o_1_1 (file)
unlock(ok): o_1_2 (file)
unlock(ok): o_2_1 (file)      <- sweep 2's outputs
unlock(ok): o_2_2 (file)
run (ok: 6)
```

which is the failure mode #7899 describes, one level up.

**In fairness: this is pre-existing, not introduced by the PR.** Stock
datalad cross-wraps too, on the occasions it manages to produce the records
at all — it usually loses them first. But it is the property the third
measure claims (*"Only a run's own commits are wrapped into its merge
commit … Without this, a concurrent run's record would end up on the second
parent of an unrelated run's merge"*), and by making nested+concurrent runs
succeed the PR makes the residual misattribution reliably reachable where
record loss previously masked it.

The mechanism is that `_has_own_commits()` gates only the *boolean*:

```python
cmd_made_commits = (... and _has_own_commits(ds.repo, pre_cmd_hexsha, post_cmd_hexsha, run_token))
...
since=pre_cmd_hexsha if cmd_made_commits else None,
```

The ancestry token correctly establishes *whether* this run committed, but
the merge range stays `pre_cmd_hexsha..HEAD`, which spans the sibling's
commits. And once foreign commits are interleaved on one linear chain, no
single second parent can cover only one run's own — so narrowing the range
is not sufficient either. Options: fall back to a plain commit of the
declared outputs when the range contains run commits belonging to another
run (the ancestry token already identifies them), or state it as a
limitation. Either seems reasonable; silently producing a merge that
`rerun` then acts on is the part worth avoiding.

## Minor

- `_lock_save()` reimplements what `datalad.support.locking` already
  provides. `try_lock_informatively()` reports *which* PID holds the lock
  and supports timeouts, where the current `acquire()` blocks indefinitely
  after a single info message. Not a correctness issue —
  `InterProcessLock` is fcntl-based, so a dead holder releases — but the
  diagnostics are better and it is one code path rather than two.
- `_execute_command()` now always passes an explicit `env` where it
  previously passed `None` and inherited. Worth confirming `WitlessRunner`
  treats an explicit copy of `os.environ` identically to inheriting it.
- `DATALAD_RUN_ANCESTRY` is exported into the command's environment, and
  will be inherited by anything the command leaves running behind it.
- Targeting: the input check turns previously-working calls into
  `impossible` and adds a configuration variable. That is a lot for a
  `maint` branch — `master` looks like the better home, while the
  #7899/#7900 fixes are true bugfixes that could go to `maint` on their
  own. Noted only because the description asks.

## Summary

The two reported defects are genuinely fixed and hold at 64-way
parallelism, and the nested+concurrent case that motivated them is solid,
including with annexed binary payloads. Finding 1 is a real regression in a
case that works today and looks worth addressing before merge. Finding 2 is
pre-existing; documenting it as a limitation would be fine, as long as it
is not described as fixed.

The design document deserves a note of its own: it made this reviewable as
reasoning rather than as a diff, and both findings above came out of
testing the properties it states rather than out of reading the code.

## Reproducers

POSIX `sh`, each using `mktemp -d` and leaving its directory behind for
inspection. Run any of them with a `datalad` of the version under test
first on `PATH`.


<details>
<summary><b>PR7901-FLAT</b> — <code>datalad-pr7901-flat-concurrency.sh</code> — flat concurrency: N runs, one output each, strict attribution check</summary>

```sh
#!/bin/sh
# Check (datalad PR #7901 review): N concurrent `run --explicit`, each
# declaring one distinct output.
#
# Verifies not just that N run records exist, but that every run commit
# contains *exactly* its own declared output -- the misattribution property
# gh-7899 is about, which a record count alone does not establish.
#
# datalad 1.6.2 (stock):  1-2 records of N, index.lock crashes at N=8
# datalad PR #7901:       N/N records, 0 mismatches, at N=8/16/32/64
#
# Usage: sh datalad-pr7901-flat-concurrency.sh [N]
#
# The temp directory is deliberately left behind for inspection.

set -eu

N="${1:-8}"
D="$(mktemp -d "${TMPDIR:-/tmp}/dl-pr7901-flat-XXXXXXX")"
datalad create -c text2git "$D/ds" >/dev/null 2>&1
cd "$D/ds"

i=1
while [ "$i" -le "$N" ]; do
    datalad run --explicit --output "o$i" -m "cell $i" \
        "python3 -c \"open('o$i','w').write('x'*1000)\"" >/dev/null 2>&1 &
    i=$((i + 1))
done
wait || true

records="$(git log --format=%s | grep -c '^\[DATALAD RUNCMD\]' || true)"
bad=0
for c in $(git log --format=%H --grep='^\[DATALAD RUNCMD\]'); do
    declared="$(git log -1 --format=%B "$c" | python3 -c "
import sys, json
text = sys.stdin.read()
record = text.split('=== Do not change lines below ===')[1].split('^^^')[0]
print(' '.join(sorted(json.loads(record)['outputs'])))
")"
    committed="$(git show --pretty=format: --name-only "$c" \
        | grep -v '^$' | sort | tr '\n' ' ' | sed 's/ $//')"
    [ "$declared" = "$committed" ] || {
        echo "  MISMATCH $(git log -1 --format=%s "$c"):"
        echo "    declared=[$declared] committed=[$committed]"
        bad=$((bad + 1))
    }
done

untracked="$(git status --porcelain | wc -l | tr -d ' ')"
merges="$(git log --format='%H %P' | awk 'NF>2' | wc -l | tr -d ' ')"
echo "N=$N records=$records/$N mismatched=$bad untracked=$untracked merges=$merges"
echo "($D)"
[ "$records" -eq "$N" ] && [ "$bad" -eq 0 ] && [ "$untracked" -eq 0 ] \
    && echo "=> PASS" || echo "=> FAIL"
```

</details>

<details>
<summary><b>PR7901-OUTER</b> — <code>datalad-pr7901-outer-parallel.sh</code> — one outer run, N inner runs in parallel</summary>

```sh
#!/bin/sh
# Check (datalad PR #7901 review): ONE outer `run --explicit` whose command
# launches N inner `run --explicit` invocations in parallel.
#
# This is nesting and concurrency at once, and it is the shape a parallel
# sweep with per-cell provenance actually takes. Expected: 1 outer record,
# N inner records, each inner commit holding exactly its own output.
#
# Usage: sh datalad-pr7901-outer-parallel.sh [N]
#
# The temp directory is deliberately left behind for inspection.

set -eu

N="${1:-8}"
D="$(mktemp -d "${TMPDIR:-/tmp}/dl-pr7901-outer-XXXXXXX")"
datalad create -c text2git "$D/ds" >/dev/null 2>&1
cd "$D/ds"

cat > sweep.sh <<INNER
#!/bin/sh
set -eu
i=1
while [ "\$i" -le $N ]; do
    datalad run --explicit --output "o\$i" -m "cell \$i" \\
        "python3 -c \\"open('o\$i','w').write('x')\\"" &
    i=\$((i + 1))
done
wait
echo done > summary.txt
INNER
chmod +x sweep.sh
datalad save -m "add sweep script" sweep.sh >/dev/null 2>&1

set +e
datalad run --explicit --output summary.txt -m "sweep" ./sweep.sh >"$D/out" 2>&1
rc=$?
set -e

outer="$(git log --format=%s | grep -c '^\[DATALAD RUNCMD\] sweep$' || true)"
inner="$(git log --format=%s | grep -c '^\[DATALAD RUNCMD\] cell ' || true)"
untracked="$(git status --porcelain | wc -l | tr -d ' ')"
bad=0
for c in $(git log --format=%H --grep='^\[DATALAD RUNCMD\] cell '); do
    declared="$(git log -1 --format=%B "$c" | python3 -c "
import sys, json
text = sys.stdin.read()
record = text.split('=== Do not change lines below ===')[1].split('^^^')[0]
print(' '.join(sorted(json.loads(record)['outputs'])))
")"
    committed="$(git show --pretty=format: --name-only "$c" \
        | grep -v '^$' | sort | tr '\n' ' ' | sed 's/ $//')"
    [ "$declared" = "$committed" ] || {
        echo "  MISMATCH: declared=[$declared] committed=[$committed]"
        bad=$((bad + 1))
    }
done

echo "N=$N outer_exit=$rc outer=$outer/1 inner=$inner/$N untracked=$untracked mismatched=$bad"
grep -o 'run(error)[^]]*]\|impossible[^]]*]' "$D/out" | head -3
echo "($D)"
[ "$rc" -eq 0 ] && [ "$outer" -eq 1 ] && [ "$inner" -eq "$N" ] \
    && [ "$untracked" -eq 0 ] && [ "$bad" -eq 0 ] \
    && echo "=> PASS" || echo "=> FAIL"
```

</details>

<details>
<summary><b>PR7901-ANNEX</b> — <code>datalad-pr7901-annex-heavy.sh</code> — the same on an annexed dataset with multi-megabyte binary payloads</summary>

```sh
#!/bin/sh
# Check (datalad PR #7901 review): the outer-parallel shape on an ANNEXED
# dataset with multi-megabyte binary payloads, rather than text2git.
#
# Usage: sh datalad-pr7901-annex-heavy.sh [N] [MB_PER_OUTPUT]
#
# The temp directory is deliberately left behind for inspection.

set -eu

N="${1:-16}"
MB="${2:-4}"
D="$(mktemp -d "${TMPDIR:-/tmp}/dl-pr7901-annex-XXXXXXX")"
datalad create "$D/ds" >/dev/null 2>&1
cd "$D/ds"

cat > sweep.sh <<INNER
#!/bin/sh
set -eu
i=1
while [ "\$i" -le $N ]; do
    datalad run --explicit --output "cell\$i.bin" -m "cell \$i" \\
        "python3 -c \\"open('cell\$i.bin','wb').write(bytes($MB*1024*1024))\\"" &
    i=\$((i + 1))
done
wait
echo done > summary.txt
INNER
chmod +x sweep.sh
datalad save -m "add sweep script" sweep.sh >/dev/null 2>&1

set +e
datalad run --explicit --output summary.txt -m "sweep" ./sweep.sh >"$D/out" 2>&1
rc=$?
set -e

outer="$(git log --format=%s | grep -c '^\[DATALAD RUNCMD\] sweep$' || true)"
inner="$(git log --format=%s | grep -c '^\[DATALAD RUNCMD\] cell ' || true)"
untracked="$(git status --porcelain | wc -l | tr -d ' ')"
bad=0
for c in $(git log --format=%H --grep='^\[DATALAD RUNCMD\] cell '); do
    declared="$(git log -1 --format=%B "$c" | python3 -c "
import sys, json
text = sys.stdin.read()
record = text.split('=== Do not change lines below ===')[1].split('^^^')[0]
print(' '.join(sorted(json.loads(record)['outputs'])))
")"
    committed="$(git show --pretty=format: --name-only "$c" \
        | grep -v '^$' | sort | tr '\n' ' ' | sed 's/ $//')"
    [ "$declared" = "$committed" ] || {
        echo "  MISMATCH: declared=[$declared] committed=[$committed]"
        bad=$((bad + 1))
    }
done

echo "N=$N size=${MB}MB exit=$rc outer=$outer/1 inner=$inner/$N untracked=$untracked mismatched=$bad"
echo "($D)"
[ "$rc" -eq 0 ] && [ "$outer" -eq 1 ] && [ "$inner" -eq "$N" ] \
    && [ "$untracked" -eq 0 ] && [ "$bad" -eq 0 ] \
    && echo "=> PASS" || echo "=> FAIL"
```

</details>

<details>
<summary><b>PR7901-INPUTS</b> — <code>datalad-pr7901-dirty-inputs.sh</code> — the declared-input check, in five false-positive-prone cases</summary>

```sh
#!/bin/sh
# Check (datalad PR #7901 review): the new declared-input check, in the
# cases most likely to produce a false positive.
#
# Expected with the PR: 1 runs, 2 is refused, 3/4/5 run.
#
# Usage: sh datalad-pr7901-dirty-inputs.sh
#
# The temp directory is deliberately left behind for inspection.

set -eu

D="$(mktemp -d "${TMPDIR:-/tmp}/dl-pr7901-inputs-XXXXXXX")"
datalad create -c text2git "$D/ds" >/dev/null 2>&1
cd "$D/ds"
mkdir -p indir
echo a > indir/a.txt
echo s > script.sh
datalad save -m init >/dev/null 2>&1

report() { grep -E 'run\(ok\)|run\(impossible\)' | head -1 | cut -c1-120; }

echo "1. clean declared input (expect: runs)"
datalad run --explicit --input indir/a.txt --output out1 \
    "python3 -c \"open('out1','w').write('1')\"" 2>&1 | report

echo "2. MODIFIED declared input (expect: impossible)"
echo mod >> indir/a.txt
datalad run --explicit --input indir/a.txt --output out2 \
    "python3 -c \"open('out2','w').write('2')\"" 2>&1 | report
git checkout indir/a.txt

echo "3. untracked file merely INSIDE a declared directory input (expect: runs)"
echo new > indir/untracked.txt
datalad run --explicit --input indir --output out3 \
    "python3 -c \"open('out3','w').write('3')\"" 2>&1 | report

echo "4. dirty file that is NOT a declared input (expect: runs)"
echo dirt >> script.sh
datalad run --explicit --input indir/a.txt --output out4 \
    "python3 -c \"open('out4','w').write('4')\"" 2>&1 | report

echo "5. --assume-ready=inputs on a modified input (expect: runs)"
echo mod >> indir/a.txt
datalad run --explicit --assume-ready=inputs --input indir/a.txt --output out5 \
    "python3 -c \"open('out5','w').write('5')\"" 2>&1 | report

echo "($D)"
```

</details>

<details>
<summary><b>PR7901-SUBDS</b> — <code>datalad-pr7901-subdataset-concurrent.sh</code> — finding 1: superdataset run with an output in a subdataset, concurrent with a run in that subdataset</summary>

```sh
#!/bin/sh
# Reproducer (datalad PR #7901 review): a `run --explicit` in a superdataset
# whose declared output lives in a subdataset, concurrent with a
# `run --explicit` inside that subdataset.
#
# The lock introduced by the PR is taken on the dataset the run was invoked
# in, but a recursive save writes to the subdataset's index too, so the two
# runs serialize on different locks and race on the same index.
#
# datalad 1.6.2 (stock):     8/8 trials both runs succeed
# datalad PR #7901:          4/8 trials, and a declared output is left
#                            untracked with no run record
#
# Usage: sh datalad-pr7901-subdataset-concurrent.sh [TRIALS]
#
# The temp directories are deliberately left behind for inspection.

set -eu

TRIALS="${1:-8}"
ok=0
t=1
while [ "$t" -le "$TRIALS" ]; do
    D="$(mktemp -d "${TMPDIR:-/tmp}/dl-pr7901-subds-XXXXXXX")"
    ( cd "$D" \
      && datalad create -c text2git ds >/dev/null 2>&1 \
      && datalad create -c text2git -d ds ds/sub >/dev/null 2>&1 )
    cd "$D/ds"

    ( datalad run --explicit --output "sub/a1" -m "super" \
        "python3 -c \"open('sub/a1','w').write('x')\"" >"$D/super.log" 2>&1
      echo "super=$?" >>"$D/rc" ) &
    ( cd "$D/ds/sub" \
      && datalad run --explicit --output "b1" -m "sub" \
        "python3 -c \"open('b1','w').write('x')\"" >"$D/sub.log" 2>&1
      echo "sub=$?" >>"$D/rc" ) &
    wait || true

    printf 'trial %s: exits: %-18s super_rec=%s sub_untracked=%s %s\n' \
        "$t" \
        "$(sort "$D/rc" | tr '\n' ' ')" \
        "$(git log --format=%s | grep -c RUNCMD || true)" \
        "$(git -C sub status --porcelain | wc -l | tr -d ' ')" \
        "$(grep -ho "pathspec '[^']*' did not match\|Unable to create[^:]*index.lock" \
             "$D"/*.log | head -1)"
    grep -q 'super=0' "$D/rc" && grep -q 'sub=0' "$D/rc" && ok=$((ok + 1))
    cd /
    t=$((t + 1))
done
echo "both runs succeeded in $ok of $TRIALS trials"
```

</details>

<details>
<summary><b>PR7901-NESTED-CONC</b> — <code>datalad-pr7901-nested-concurrent.sh</code> — finding 2: concurrent outer runs, each performing inner runs</summary>

```sh
#!/bin/sh
# Reproducer (datalad PR #7901 review): N concurrent OUTER `run --explicit`
# invocations, each of which performs inner `run`s of its own.
#
# Each outer run's merge commit wraps everything committed since its own
# pre-command HEAD, which under concurrency includes the sibling's inner
# commits. `datalad rerun` of one outer record then re-executes the other
# sweep's commands.
#
# Pre-existing (stock datalad shows it too, when it manages to produce the
# records at all), but not fixed by the PR, whose stated property is that
# "only a run's own commits are wrapped into its merge commit".
#
# Usage: sh datalad-pr7901-nested-concurrent.sh [N]
#
# The temp directory is deliberately left behind for inspection.

set -eu

N="${1:-2}"
D="$(mktemp -d "${TMPDIR:-/tmp}/dl-pr7901-nc-XXXXXXX")"
datalad create -c text2git "$D/ds" >/dev/null 2>&1
cd "$D/ds"
# so that stock datalad can run the nested case at all
git config datalad.run.dirty-committed ignore

cat > sweep.sh <<'INNER'
#!/bin/sh
set -eu
S="$1"
for i in 1 2; do
    datalad run --explicit --output "o_${S}_$i" -m "cell $S.$i" \
        "python3 -c \"open('o_${S}_$i','w').write('x')\""
done
echo done > "summary_$S.txt"
INNER
chmod +x sweep.sh
datalad save -m "add sweep script" sweep.sh >/dev/null 2>&1

s=1
while [ "$s" -le "$N" ]; do
    datalad run --explicit --output "summary_$s.txt" -m "sweep $s" \
        "./sweep.sh $s" >"$D/out.$s" 2>&1 &
    s=$((s + 1))
done
wait || true

bad=0
for c in $(git log --format='%H %P' | awk 'NF>2 {print $1}'); do
    subject="$(git log -1 --format=%s "$c")"
    mine="$(echo "$subject" | sed -n 's/.*sweep \([0-9]*\).*/\1/p')"
    [ -n "$mine" ] || continue
    p1="$(git log -1 --format=%P "$c" | cut -d' ' -f1)"
    p2="$(git log -1 --format=%P "$c" | cut -d' ' -f2)"
    foreign="$(git log --format=%s "$p1..$p2" 2>/dev/null \
        | sed -n 's/^\[DATALAD RUNCMD\] cell \([0-9]*\)\..*/\1/p' \
        | grep -cv "^$mine$" || true)"
    [ "$foreign" -eq 0 ] || {
        echo "  '$subject' wraps $foreign cell commit(s) of another sweep"
        bad=$((bad + 1))
    }
done

echo "outer=$(git log --format=%s | grep -c 'RUNCMD] sweep' || true)/$N" \
     "inner=$(git log --format=%s | grep -c 'RUNCMD] cell' || true)/$((N * 2))" \
     "cross_wrapping_merges=$bad"
echo "graph:"
git log --graph --format='%h %p | %s' | head -20
echo "($D)"
```

</details>
