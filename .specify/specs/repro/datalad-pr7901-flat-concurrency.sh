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
