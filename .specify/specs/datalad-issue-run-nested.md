# ISSUE DRAFT 2 — nested `datalad run`: outer run rejects commits made by inner runs unless it re-declares every inner output

*(Ready to file at github.com/datalad/datalad. Body below the line.
Reproducer script: `.specify/specs/repro/datalad-run-nested.sh`)*

---

## Summary

An outer `datalad run --explicit` whose command performs its own inner
`datalad run` calls fails with

```
command created commits that include files not declared as --output: ['o1', 'o2'].
Set config datalad.run.dirty-committed=ignore to override
```

unless the outer run re-declares every output every inner run produces.

The files in question are not stray side effects — each one was committed
by a `datalad run` of its own and carries a complete, correct run record.
The outer run is refusing work that is *more* provenance-complete than the
undeclared-side-effect case the check exists to catch.

This is serial, single-threaded behaviour. It is unrelated to the
concurrency race filed separately.

## Versions

```
datalad 1.6.2
git 2.47.3
git-annex 10.20260717-g698698a3c787a39d6ebe444d85b3eed81a60fb2d
Python 3.13.5, Debian 13 (trixie), glibc 2.41
```

## Reproducer

Two variants, each in its own fresh dataset. `sweep.sh` is the outer run's
command; it performs two inner `datalad run` calls and then writes its own
summary file.

```sh
#!/bin/sh
set -eu

ROOT="$(mktemp -d "${TMPDIR:-/tmp}/dl-nested-XXXXXXX")"
echo "root: $ROOT"

make_ds() {
    datalad create -c text2git "$1" >/dev/null 2>&1
    cat > "$1/sweep.sh" <<'INNER'
#!/bin/sh
set -eu
for i in 1 2; do
    datalad run --explicit --output "o$i" -m "cell $i" \
        "python3 -c \"open('o$i','w').write('x')\""
done
echo done > summary.txt
INNER
    chmod +x "$1/sweep.sh"
    ( cd "$1" && datalad save -m "add sweep script" sweep.sh >/dev/null 2>&1 )
}

# Variant A: outer re-declares every inner output
make_ds "$ROOT/a"; cd "$ROOT/a"
datalad run --explicit --output o1 --output o2 --output summary.txt \
    -m "sweep" ./sweep.sh; echo "A exit: $?"

# Variant B: outer declares only its own output
make_ds "$ROOT/b"; cd "$ROOT/b"
datalad run --explicit --output summary.txt -m "sweep" ./sweep.sh; echo "B exit: $?"
```

## Actual result

```
=== Variant A: outer declares o1, o2 and summary.txt ===
  exit code : 0
  records   : 3
  untracked :
  chain     : [] [] []

=== Variant B: outer declares only summary.txt ===
  exit code : 1
  records   : 2
  untracked : ?? summary.txt
  chain     : [] []
  message   : run(error): .../b (dataset) [command created commits that include
              files not declared as --output: ['o1', 'o2'].
              Set config datalad.run.dirty-committed=ignore to override]
```

Variant B leaves the outer run's own declared output, `summary.txt`,
uncommitted and untracked, with no outer run record — the two inner records
survive, so the dataset is left half-recorded.

## Expected result

Variant B should succeed. Files committed by a nested `datalad run` are
fully recorded and should not count as undeclared side effects of the outer
command.

## Why the current workarounds are unsatisfying

**Re-declaring every inner output (variant A)** requires the outer run to
enumerate, up front, every file every inner cell will produce. For a sweep
whose cell list is computed at runtime that is not merely verbose — it is
not knowable when the outer command line is constructed. It also duplicates
the declaration, so the two can silently drift apart.

**`datalad.run.dirty-committed=ignore`** is a dataset-wide override that
disables the check entirely, including for the genuine mistakes it exists
to catch. A narrower value — meaning "commits produced by a nested
`datalad run` are expected" — would keep the protection while permitting
the nesting.

## Secondary: `chain` is never populated

`chain` is `[]` on every record in both variants, including variant A where
nesting demonstrably occurred and succeeded. If `chain` is the field
intended to express the outer/inner relationship, it does not appear to be
populated; the nesting is recoverable only by inspecting commit order.

## Why this matters

Per-sweep *and* per-cell provenance is exactly what nested run promises: an
outer record saying "this sweep was run this way", inner records saying
"and this cell within it was computed like so". Variant B is the natural
shape of that — the outer command owns a summary, each cell owns its own
outputs — and it is the one that fails.
