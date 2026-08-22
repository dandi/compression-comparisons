#!/bin/sh
# Post the PR #7901 review to GitHub.
#
# Dry-run by default: prints exactly what would be sent and exits without
# touching the network. Posting is a public, outward-facing action, so it
# requires the explicit --post flag.
#
# Usage:
#   sh post-pr7901-review.sh                  # dry run, show the payload
#   sh post-pr7901-review.sh --post           # post as a review comment
#   sh post-pr7901-review.sh --post --request-changes
#   sh post-pr7901-review.sh --no-repro       # omit the inlined reproducers
#
# Requires: gh, authenticated (`gh auth login`, or GH_TOKEN in the env).

set -eu

PR=7901
REPO=datalad/datalad
HERE="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
REVIEW="$HERE/datalad-pr7901-review.md"
REPRO_DIR="$HERE/repro"

POST=0
EVENT=comment
WITH_REPRO=1

for arg in "$@"; do
    case "$arg" in
        --post)            POST=1 ;;
        --request-changes) EVENT=request-changes ;;
        --approve)         EVENT=approve ;;
        --no-repro)        WITH_REPRO=0 ;;
        -h|--help)         sed -n '2,15p' "$0"; exit 0 ;;
        *) echo "unknown argument: $arg" >&2; exit 2 ;;
    esac
done

[ -f "$REVIEW" ] || { echo "review not found: $REVIEW" >&2; exit 1; }

BODY="$(mktemp "${TMPDIR:-/tmp}/pr7901-body-XXXXXXX.md")"

# The review file carries a local header; the postable body is everything
# after the first line that is exactly '---'.
awk 'found { print; next } /^---$/ { found = 1 }' "$REVIEW" > "$BODY"

[ -s "$BODY" ] || { echo "extracted body is empty -- check the '---' marker in $REVIEW" >&2; exit 1; }

# Inline the reproducers so the comment stands on its own: a reader of the
# PR cannot see paths in our repository.
if [ "$WITH_REPRO" -eq 1 ]; then
    for f in datalad-pr7901-subdataset-concurrent.sh \
             datalad-pr7901-nested-concurrent.sh; do
        [ -f "$REPRO_DIR/$f" ] || { echo "missing reproducer: $REPRO_DIR/$f" >&2; exit 1; }
        {
            printf '\n<details>\n<summary><code>%s</code></summary>\n\n' "$f"
            printf '```sh\n'
            cat "$REPRO_DIR/$f"
            printf '```\n\n</details>\n'
        } >> "$BODY"
    done
fi

echo "== target   : $REPO#$PR"
echo "== event    : $EVENT"
echo "== body     : $BODY ($(wc -c < "$BODY" | tr -d ' ') bytes, $(wc -l < "$BODY" | tr -d ' ') lines)"
echo "== reproducers inlined: $WITH_REPRO"
echo

if [ "$POST" -ne 1 ]; then
    echo "--- DRY RUN, nothing sent. Body follows; re-run with --post to submit. ---"
    echo
    cat "$BODY"
    exit 0
fi

command -v gh >/dev/null || { echo "gh not found on PATH" >&2; exit 1; }
gh auth status >/dev/null 2>&1 || {
    echo "gh is not authenticated. Run 'gh auth login', or export GH_TOKEN." >&2
    exit 1
}

# A review cannot be submitted on one's own pull request; fall back to a
# plain issue comment in that case, which carries the same content.
if gh pr review "$PR" --repo "$REPO" "--$EVENT" --body-file "$BODY"; then
    echo "posted as a review ($EVENT)"
else
    echo "review submission failed -- falling back to a plain PR comment" >&2
    gh pr comment "$PR" --repo "$REPO" --body-file "$BODY"
    echo "posted as a comment"
fi

echo "https://github.com/$REPO/pull/$PR"
