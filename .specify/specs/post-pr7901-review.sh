#!/bin/sh
# Post the PR #7901 review bundle to GitHub.
#
# The bundle (datalad-pr7901-review.md) is self-contained: prose plus every
# reproducer embedded. This script only strips the local header and sends it.
#
# Dry-run by default: prints exactly what would be sent and exits without
# touching the network. Posting is public and not easily undone, so it takes
# an explicit --post.
#
# Usage:
#   sh post-pr7901-review.sh                     # dry run, show the payload
#   sh post-pr7901-review.sh --post              # post as a review comment
#   sh post-pr7901-review.sh --post --request-changes
#   sh post-pr7901-review.sh --bundle datalad-pr7901-review-2.md --post
#
# Requires: gh, authenticated (`gh auth login`, or GH_TOKEN in the env).

set -eu

PR=7901
REPO=datalad/datalad
HERE="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
BUNDLE="$HERE/datalad-pr7901-review.md"

# GitHub rejects a comment body above this many characters
MAX_BODY=65536

POST=0
EVENT=comment

expect_bundle=0
for arg in "$@"; do
    if [ "$expect_bundle" -eq 1 ]; then
        case "$arg" in
            /*) BUNDLE="$arg" ;;
            *)  BUNDLE="$HERE/$arg" ;;
        esac
        expect_bundle=0
        continue
    fi
    case "$arg" in
        --bundle)          expect_bundle=1 ;;
        --post)            POST=1 ;;
        --request-changes) EVENT=request-changes ;;
        --approve)         EVENT=approve ;;
        -h|--help)         sed -n '2,19p' "$0"; exit 0 ;;
        *) echo "unknown argument: $arg" >&2; exit 2 ;;
    esac
done
[ "$expect_bundle" -eq 0 ] || { echo "--bundle needs a file argument" >&2; exit 2; }

[ -f "$BUNDLE" ] || { echo "bundle not found: $BUNDLE" >&2; exit 1; }

BODY="$(mktemp "${TMPDIR:-/tmp}/pr7901-body-XXXXXXX.md")"

# The postable body is everything after the first line that is exactly '---'
awk 'found { print; next } /^---$/ { found = 1 }' "$BUNDLE" > "$BODY"

[ -s "$BODY" ] || {
    echo "extracted body is empty -- check the '---' marker in $BUNDLE" >&2
    exit 1
}

size="$(wc -c < "$BODY" | tr -d ' ')"
[ "$size" -le "$MAX_BODY" ] || {
    echo "body is $size characters, over GitHub's $MAX_BODY limit" >&2
    exit 1
}

echo "== bundle : $BUNDLE"
echo "== target : $REPO#$PR"
echo "== event  : $EVENT"
echo "== body   : $BODY ($size chars, $(wc -l < "$BODY" | tr -d ' ') lines)"
echo "== embedded reproducers: $(grep -c '^<details>' "$BODY" || true)"
echo

if [ "$POST" -ne 1 ]; then
    echo "--- DRY RUN, nothing sent. Re-run with --post to submit. ---"
    echo
    cat "$BODY"
    exit 0
fi

command -v gh >/dev/null || { echo "gh not found on PATH" >&2; exit 1; }
gh auth status >/dev/null 2>&1 || {
    echo "gh is not authenticated. Run 'gh auth login', or export GH_TOKEN." >&2
    exit 1
}

# GitHub refuses a formal review on one's own pull request; fall back to a
# plain issue comment, which carries identical content.
if gh pr review "$PR" --repo "$REPO" "--$EVENT" --body-file "$BODY"; then
    echo "posted as a review ($EVENT)"
else
    echo "review submission failed -- falling back to a plain PR comment" >&2
    gh pr comment "$PR" --repo "$REPO" --body-file "$BODY"
    echo "posted as a comment"
fi

echo "https://github.com/$REPO/pull/$PR"
