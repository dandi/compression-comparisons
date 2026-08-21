# ISSUE DRAFT 1 — `datalad run --explicit`: concurrent runs commit each other's outputs and silently lose run records

*(Ready to file at github.com/datalad/datalad. Body below the line.
Reproducer script: `.specify/specs/repro/datalad-run-explicit-concurrency.sh`)*

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

Takes the concurrency level as `$1`, default 2. Each run declares exactly
one distinct output.

```sh
#!/bin/sh
set -eux
PS4='> '

N="${1:-2}"

cd "$(mktemp -d "${TMPDIR:-/tmp}/dl-explicit-conc-XXXXXXX")"
pwd

datalad create -c text2git ds
cd ds

i=1
while [ "$i" -le "$N" ]; do
    datalad run --explicit --output "o$i" -m "cell $i" \
        "python3 -c \"open('o$i','w').write('x')\"" &
    i=$((i + 1))
done
wait

set +x
echo "=== commits ==="
git log --format='%h %s' --name-only
echo "=== run records: $(git log --format=%s | grep -c '^\[DATALAD RUNCMD\]') of $N expected ==="
echo "=== git status (empty means every output is tracked) ==="
git status --porcelain
echo "=== run record of HEAD ==="
git log -1 --format=%B | sed -n '/^=== Do not change lines below/,$p'
```

## Actual result

Both invocations exit 0 and both report `save(ok)`:

```
run(ok): .../ds (dataset) [python3 -c "open('o2','w').write('x')"]
add(ok): o2 (file)
save(ok): . (dataset)
run(ok): .../ds (dataset) [python3 -c "open('o1','w').write('x')"]
add(ok): o1 (file)
save(ok): . (dataset)          <- no commit was created for this one
```

One run commit exists, containing both outputs:

```
=== commits ===
91837fc [DATALAD RUNCMD] cell 2

o1
o2
=== run records: 1 of 2 expected ===
=== git status (empty means every output is tracked) ===
```

and its record declares a single output:

```json
{
 "chain": [],
 "cmd": "python3 -c \"open('o2','w').write('x')\"",
 "exit": 0,
 "inputs": [],
 "outputs": [
  "o2"
 ],
 "pwd": "."
}
```

`o1` is committed inside a run record stating it produced only `o2`. The
command that actually created `o1` is recorded nowhere. `git status` is
clean.

## Expected result

Two commits, each recording one command and containing only that command's
declared output — or, failing that, a hard error. Not a success report
with missing and misattributed provenance.

## Reproducibility

Running the script above as-is: **12 of 12 trials lost at least one run
record**, across four concurrency levels, three trials each.

| concurrency | trials | run records created (of N) | outputs left untracked |
| ----------: | -----: | :------------------------- | ---------------------: |
|           2 |      3 | 1, 1, 1                    |                      0 |
|           3 |      3 | 1, 2, 1                    |                      0 |
|           4 |      3 | 1, 1, 1                    |                      0 |
|           8 |      3 | 2, 1, 2                    |                      0 |

Every output file is always written and always ends up tracked; only the
records go missing.

At higher concurrency a second, *visible* failure also appears — a plain
index-lock race on the final commit, in **4 of 6** further trials at N=8:

```
CommandError: 'git -c diff.ignoreSubmodules=none -c core.quotepath=false \
  commit -m '[DATALAD RUNCMD] cell 1 ...' failed with exitcode 128
  [err: 'fatal: Unable to create '.../ds/.git/index.lock': File exists.
```

The command itself always succeeds; only the commit fails, and neither git
nor datalad retries.

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

## See also

Nested `datalad run` — the other half of what we wanted here, per-sweep and
per-cell records simultaneously — is filed separately: it is serial, not a
race, and has a different cause.
