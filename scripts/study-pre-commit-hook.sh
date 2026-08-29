#!/bin/sh
# pre-commit hook for the STAMPED study dataset.
#
# Refuses a commit that touches anything outside derivatives/ while a sweep
# is running. Such a commit lands inside some in-flight cell's `datalad run`
# window; the cell then fails with "command created commits that include
# files not declared as --output", and snakemake DELETES that cell's
# completed outputs. One careless commit cost 10 finished cells on
# 2026-08-23.
#
# `datalad run`'s own per-cell commits touch only derivatives/, so they pass
# untouched -- that is the distinction this hook relies on. Getting that
# wrong would block the sweep's own commits, which is worse than the problem
# being prevented, so the derivatives-only check is deliberately the ONLY
# thing standing between a commit and success.
#
# Install:  cp scripts/study-pre-commit-hook.sh \
#             results/dandi-t261-compression-study/.git/hooks/pre-commit
# Override: COMPBENCH_ALLOW_COMMIT_DURING_SWEEP=1 git commit ...

set -eu

# nothing running -> nothing to protect
# The dangerous window is wider than "a cell is running": a sweep's OUTER
# `datalad run` stays open after its last cell finishes, and a plain commit
# landing then is rejected as an undeclared change. That is how the
# 96/96-complete T.261 sweep lost its sweep-level record on 2026-08-29.
# So watch for the wrapping `datalad run` and for snakemake too, not just
# for compbench workers.
if ! pgrep -f '[c]ompbench (run|compress|spikesort|compare-sorting)' >/dev/null 2>&1 \
   && ! pgrep -f '[s]nakemake -s .*compbench' >/dev/null 2>&1 \
   && ! pgrep -f '[d]atalad run .*--output derivatives' >/dev/null 2>&1; then
    exit 0
fi

if [ -n "${COMPBENCH_ALLOW_COMMIT_DURING_SWEEP:-}" ]; then
    exit 0
fi

# A commit made BY `datalad run` is safe even mid-sweep: it carries a run
# record, and a concurrent run's dirty-committed check accepts recorded
# commits (that is the gh-7900 fix). Only PLAIN commits are the hazard.
# DATALAD_RUN_ANCESTRY is set by `run` in its command's environment, so its
# presence means this commit will be recorded. Verified: a `datalad run`
# touching code/ concurrently with a cell writing derivatives/ leaves both
# at exit 0 with both records intact.
if [ -n "${DATALAD_RUN_ANCESTRY:-}" ]; then
    exit 0
fi

# staged paths, against HEAD or against the empty tree on a first commit
if git rev-parse --verify HEAD >/dev/null 2>&1; then
    staged=$(git diff --cached --name-only)
else
    staged=$(git diff --cached --name-only \
        "$(git hash-object -t tree /dev/null)")
fi

# a commit touching only derivatives/ is what `datalad run` itself makes
outside=$(printf '%s\n' "$staged" | grep -v '^derivatives/' | grep -v '^$' || true)
[ -n "$outside" ] || exit 0

cells=$(pgrep -af '[c]ompbench (run|compress|spikesort|compare-sorting)' 2>/dev/null \
    | grep -oE '\-\-output-dir [^ ]+' | sort -u | wc -l | tr -d ' ')

cat >&2 <<MSG
REFUSED: a sweep is running ($cells cells in flight) and this commit touches
files outside derivatives/:

$(printf '%s\n' "$outside" | sed 's/^/  /')

Any commit on this branch lands inside an in-flight cell's \`datalad run\`
window. That cell fails with "command created commits that include files not
declared as --output", and snakemake deletes its completed outputs -- work
that has already finished is thrown away.

Do one of:
  * write to a gitignored path (.partial-reports/) instead;
  * commit to the tool repo, which is a separate git repository;
  * wait for the sweep to finish, then commit.

To override (you are sure no cell is mid-save):
  COMPBENCH_ALLOW_COMMIT_DURING_SWEEP=1 git commit ...
MSG
exit 1
