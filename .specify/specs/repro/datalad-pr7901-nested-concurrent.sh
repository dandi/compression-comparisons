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
