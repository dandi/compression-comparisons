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
