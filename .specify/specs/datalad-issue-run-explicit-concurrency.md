# ISSUE DRAFT — `datalad run --explicit`: concurrent runs commit each other's outputs and silently lose run records

*(Ready to file at github.com/datalad/datalad. Body below the line.)*

---

## Summary

With `--explicit`, `datalad run` commits files it did not declare as
`--output`. When two `--explicit` runs execute concurrently in one dataset,
one commit absorbs the other's outputs, and the losing run exits **0**
having produced **no run record at all**. The result is a dataset where
every file is tracked, the tree is clean, both commands reported success —
and the recorded provenance is wrong.

This is scoped deliberately to `--explicit`. Without it, committing
everything the command produced is the documented behaviour and not at
issue. `--explicit` documents the opposite: *"only save modifications to
the listed outputs"*. That is the contract being broken.

## Versions

```
datalad 1.6.2
git 2.47.3
git-annex 10.20260717-g698698a3c787a39d6ebe444d85b3eed81a60fb2d
Python 3.13.5, Debian 13 (trixie), glibc 2.41
local btrfs filesystem, single host, no network filesystem
```

## Reproducer

Two concurrent runs, each declaring exactly one distinct output:

```bash
D=/var/tmp/dl-issue; rm -rf $D
datalad create -c text2git $D; cd $D

for i in 1 2; do
  ( datalad run --explicit --output "o$i" -m "cell $i" \
      "python3 -c \"open('o$i','w').write('x')\"" ) &
done
wait

git log --format='%h %s' --name-only
git status --porcelain
```

## Actual result

Both invocations exit 0. One commit exists:

```
f9e8433 [DATALAD RUNCMD] cell 2

o1
o2
```

Its run record declares a single output:

```json
{
 "cmd": "python3 -c \"open('o2','w').write('x')\"",
 "inputs": [],
 "outputs": ["o2"],
 "exit": 0
}
```

`o1` is committed inside a run record that states it produced only `o2`.
The command that actually created `o1` is recorded nowhere. `git status`
is clean.

Both logs claim to have saved:

```
# cell 1
run(ok): /var/tmp/dl-issue (dataset) [python3 -c "open('o1','w').write('x')"]
add(ok): o1 (file)
save(ok): . (dataset)          <- but no commit was created

# cell 2
run(ok): /var/tmp/dl-issue (dataset) [python3 -c "open('o2','w').write('x')"]
add(ok): o2 (file)
save(ok): . (dataset)
```

## Expected result

Two commits, each recording one command and containing only that command's
declared output — or, failing that, a hard error. Not a success report
with missing and misattributed provenance.

## Reproducibility

At N=2, **6 of 6 trials** lost a record. Scaling the same reproducer:

| concurrency | exit 0 | run records created | outputs left untracked |
| ----------: | -----: | ------------------: | ---------------------: |
|           2 |    2/2 |                   1 |                      0 |
|           3 |    3/3 |                   2 |                      0 |
|           4 |    3/4 |                   1 |                      0 |
|           8 |    6/8 |                   2 |                      0 |

Successful exits consistently exceed records created. At higher
concurrency a second, *visible* failure also appears — a plain index-lock
race on the final commit:

```
CommandError: 'git -c diff.ignoreSubmodules=none -c core.quotepath=false \
  commit -m '[DATALAD RUNCMD] cell 1 ...' failed with exitcode 128
  [err: 'fatal: Unable to create '/var/tmp/dl-conc/.git/index.lock': File exists.
```

The command itself always succeeds; every output file is written. Only the
commit fails, and neither git nor datalad retries.

## Analysis

`--explicit` stages the declared outputs and then invokes `git commit`
without a pathspec. The index is shared dataset state, so:

1. A stages `o1`; B stages `o2`.
2. B commits — sweeping in `o1`, which it never declared.
3. A finds nothing left to commit and returns without creating a record.

The index-lock crash and the silent misattribution are the same race with
different timing. **The crash is the benign outcome** — it is visible. The
silent case produces a dataset that looks correct and is not.

## Why this matters

The reason to use `datalad run` at all is that the record is trustworthy.
A record that confidently names the wrong command is worse than no record,
because nothing downstream can detect it: exit status is 0, the tree is
clean, all outputs are tracked, and `datalad rerun` on that commit will
re-execute one command and re-materialise several files.

We hit this trying to give each cell of a many-hundred-cell compression
benchmark its own run record. We have fallen back to one `datalad run`
around a whole parallel sweep, with per-cell provenance carried in our own
manifests — which works but discards exactly the granularity `datalad run`
exists to provide.

## Suggested fixes

In increasing order of completeness:

1. **Commit with an explicit pathspec under `--explicit`.** The declared
   outputs are known, so `git commit -- <outputs>` prevents a sibling's
   staged files from entering the wrong commit. This alone fixes the
   misattribution, which is the dangerous half.
2. **Error when an `--explicit` run has nothing to commit.** Exiting 0
   without a record should not be reachable when the command succeeded and
   declared outputs.
3. **A dataset-scoped lock around stage + commit.** Makes concurrent `run`
   safe generally, keeping the expensive part — the command — parallel.
   Retrying on `index.lock` alone is *not* sufficient: it fixes the crash
   while leaving the silent misattribution untouched.

## Related: nested `datalad run`

While characterising this we also exercised nested runs, which would give
per-sweep and per-cell records simultaneously. Serially it works, but two
things are worth noting:

* The outer run aborts with
  `command created commits that include files not declared as --output`
  unless `datalad.run.dirty-committed=ignore` is set. That config is a
  dataset-wide override which also suppresses the check for cases where an
  undeclared commit genuinely is a mistake. A narrower value meaning
  "commits from nested `datalad run` are expected" would be safer.
* With the override, the four expected records appear and the tree is
  clean — but `chain` is `[]` on every record, inner ones included, so the
  nesting relationship is not captured in the record itself and is only
  inferable from commit order. If `chain` is intended to express this, it
  does not appear to be populated.
