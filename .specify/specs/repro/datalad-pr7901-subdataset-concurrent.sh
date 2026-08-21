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
