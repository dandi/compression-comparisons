#!/bin/sh
# Reproducer: an outer `datalad run --explicit` whose command performs its own
# inner `datalad run` calls is rejected as having made "dirty" commits, even
# though every file involved carries a complete run record of its own.
#
# Two variants are exercised, each in its own fresh dataset:
#   A. outer re-declares every output the inner runs produce  -> works
#   B. outer declares only its own output                     -> run(error)
#
# Usage: sh datalad-run-nested.sh
#
# Temp directories are deliberately left behind for inspection.

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

report() {
    echo "  exit code : $1"
    echo "  records   : $(git log --format=%s | grep -c '^\[DATALAD RUNCMD\]')"
    echo "  untracked : $(git status --porcelain | tr '\n' ' ')"
    echo "  chain     : $(git log --format=%h --grep='DATALAD RUNCMD' \
                          | while read -r c; do
                                git log -1 --format=%B "$c" \
                                | sed -n 's/.*"chain": \(\[[^]]*\]\).*/\1/p'
                            done | tr '\n' ' ')"
}

echo
echo "=== Variant A: outer declares o1, o2 and summary.txt ==="
make_ds "$ROOT/a"
cd "$ROOT/a"
set +e
datalad run --explicit --output o1 --output o2 --output summary.txt \
    -m "sweep" ./sweep.sh >"$ROOT/a.log" 2>&1
rc=$?
set -e
report "$rc"

echo
echo "=== Variant B: outer declares only summary.txt ==="
make_ds "$ROOT/b"
cd "$ROOT/b"
set +e
datalad run --explicit --output summary.txt -m "sweep" ./sweep.sh >"$ROOT/b.log" 2>&1
rc=$?
set -e
report "$rc"
echo "  message   : $(grep 'run(error)' "$ROOT/b.log" | head -1)"
