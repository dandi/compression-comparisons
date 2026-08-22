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
