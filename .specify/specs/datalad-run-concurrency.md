# `datalad run` concurrency: silent provenance corruption

Findings from trying to give every benchmark cell its own `datalad run`
record. Written up for an upstream report.

**Versions:** datalad 1.6.2 · git 2.47.3 · git-annex 10.20260717 ·
Debian 13 (trixie), glibc 2.41, Python 3.13.5. Local filesystem (btrfs),
single host, no NFS.

## The headline

Concurrent `datalad run` invocations in one dataset do not merely fail —
**they can silently attribute one command's outputs to another command's
run record, while reporting success and leaving a clean tree.**

That is worse than the crash it accompanies. A crash is visible; this is
not. A reader of the resulting dataset gets a provenance record that is
confidently wrong.

## Minimal reproducer

```bash
D=/var/tmp/dlc; rm -rf $D; datalad create -c text2git $D; cd $D
for i in 1 2 3 4 5 6 7 8; do
  ( datalad run --explicit --output "o$i" -m "c$i" \
      "python3 -c \"open('o$i','w').write('x')\"" ) &
done; wait
git log --format='%h %s' --name-only
```

## Observed

Two distinct failures, both from the same race.

### 1. Hard failure: `git commit` races on the index lock

```
CommandError: 'git -c diff.ignoreSubmodules=none -c core.quotepath=false commit -m '[DATALAD RUNCMD] cell 1 ...
  failed with exitcode 128
  [err: 'fatal: Unable to create '/var/tmp/dlc/.git/index.lock': File exists.
```

The *command* always succeeds — every output file is written. It is the
commit at the end of `datalad run` that fails. Neither git nor datalad
retries; the `CommandError` is surfaced immediately.

### 2. Silent misattribution — the serious one

Scaling the reproducer, counting successful exits against run records
actually created:

| concurrency | exit 0 | run records | outputs untracked |
| ----------: | -----: | ----------: | ----------------: |
|           2 |    2/2 |           1 |                 0 |
|           3 |    3/3 |           2 |                 0 |
|           4 |    3/4 |           1 |                 0 |
|           8 |    6/8 |           2 |                 0 |

Successes consistently exceed records. Inspecting the N=8 dataset:

```
commit cae9079  "[DATALAD RUNCMD] c2"
    record:   cmd = python3 -c "open('o2','w').write('x')"
              outputs = ["o2"]
    contains: o1  o2  o3  o6
```

`o1`, `o3` and `o6` are committed under a record that declares it produced
only `o2`. The commands that actually produced them are recorded nowhere.
Every output is tracked, the tree is clean, and six of eight invocations
reported success.

### Mechanism

`datalad run --explicit` stages its declared outputs and then invokes
`git commit`. The index is shared dataset state. If sibling B has staged
its output before A commits, A's commit sweeps B's file in; B then finds
nothing to commit and exits without a record. So the number of records is
bounded by the number of commits that win the race, not by the number of
commands run.

## What would help

1. **Serialise the commit.** A dataset-scoped lock around stage+commit
   would make concurrent `run` safe; the expensive part (the command) stays
   parallel. Retrying on `index.lock` alone is not sufficient — it fixes
   the crash but not the misattribution.
2. **Commit with an explicit pathspec.** Under `--explicit` the declared
   `--output` paths are known, so `git commit -- <outputs>` would keep a
   racing sibling's files out of the wrong commit even without a lock.
3. **Fail loudly rather than silently.** If a `run` finds nothing to
   commit because a sibling swept its outputs, that should be an error, not
   exit 0 with no record.

## Nested `datalad run` — works, with one config

Nesting is the feature that would give both levels of provenance we want
(one record per sweep, one per cell). Out of the box the outer run refuses:

```
run(error): command created commits that include files not declared as
--output: ['out/c1', 'out/c2', 'out/c3'].
Set config datalad.run.dirty-committed=ignore to override
```

With `git config datalad.run.dirty-committed ignore` it works, producing
exactly the desired structure — 4 records, tree clean:

```
acea733 [DATALAD RUNCMD] outer: sweep of 3 cells      outputs=['out']
70b1f70 [DATALAD RUNCMD] inner cell 3                 outputs=['out/c3']
84b2d44 [DATALAD RUNCMD] inner cell 2                 outputs=['out/c2']
ab5b16b [DATALAD RUNCMD] inner cell 1                 outputs=['out/c1']
```

Two observations:

* The `chain` field is `[]` on every record, including the inner ones, so
  the nesting relationship is not captured in the record itself — it is
  only inferable from commit order. If `chain` is intended to express
  this, it is not populated here.
* Requiring `dirty-committed=ignore` is a blunt instrument: it disables the
  check globally for the dataset, including for cases where a command
  committing undeclared files really is a mistake. A value meaning "inner
  `datalad run` commits are expected" would be safer than "ignore
  everything".

## What we do meanwhile

* **Sweeps** (hundreds of cells, parallel): one `datalad run` wrapping the
  whole sweep. Per-cell provenance lives in each cell's `manifest.json`
  (tool SHA, BWC SHA, codec parameters and filters, input sha256,
  git-annex key of the source recording).
* **Pipeline stages** (compress / spikesort / compare, serial): one
  `datalad run` each, which is where per-operation records are both wanted
  and safe.
* Nested per-cell records are attractive and demonstrably work when
  serial — they are blocked only by the concurrency issue above.
