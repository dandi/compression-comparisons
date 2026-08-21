#!/bin/sh
# Reproducer: `datalad run --explicit` under concurrency commits undeclared
# outputs and silently drops run records.
#
# Usage: sh datalad-run-explicit-concurrency.sh [N]   (default N=2)
#
# The temp directory is deliberately left behind for inspection.

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
