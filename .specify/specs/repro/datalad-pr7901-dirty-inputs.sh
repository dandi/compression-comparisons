#!/bin/sh
# Check (datalad PR #7901 review): the new declared-input check, in the
# cases most likely to produce a false positive.
#
# Expected with the PR: 1 runs, 2 is refused, 3/4/5 run.
#
# Usage: sh datalad-pr7901-dirty-inputs.sh
#
# The temp directory is deliberately left behind for inspection.

set -eu

D="$(mktemp -d "${TMPDIR:-/tmp}/dl-pr7901-inputs-XXXXXXX")"
datalad create -c text2git "$D/ds" >/dev/null 2>&1
cd "$D/ds"
mkdir -p indir
echo a > indir/a.txt
echo s > script.sh
datalad save -m init >/dev/null 2>&1

report() { grep -E 'run\(ok\)|run\(impossible\)' | head -1 | cut -c1-120; }

echo "1. clean declared input (expect: runs)"
datalad run --explicit --input indir/a.txt --output out1 \
    "python3 -c \"open('out1','w').write('1')\"" 2>&1 | report

echo "2. MODIFIED declared input (expect: impossible)"
echo mod >> indir/a.txt
datalad run --explicit --input indir/a.txt --output out2 \
    "python3 -c \"open('out2','w').write('2')\"" 2>&1 | report
git checkout indir/a.txt

echo "3. untracked file merely INSIDE a declared directory input (expect: runs)"
echo new > indir/untracked.txt
datalad run --explicit --input indir --output out3 \
    "python3 -c \"open('out3','w').write('3')\"" 2>&1 | report

echo "4. dirty file that is NOT a declared input (expect: runs)"
echo dirt >> script.sh
datalad run --explicit --input indir/a.txt --output out4 \
    "python3 -c \"open('out4','w').write('4')\"" 2>&1 | report

echo "5. --assume-ready=inputs on a modified input (expect: runs)"
echo mod >> indir/a.txt
datalad run --explicit --assume-ready=inputs --input indir/a.txt --output out5 \
    "python3 -c \"open('out5','w').write('5')\"" 2>&1 | report

echo "($D)"
