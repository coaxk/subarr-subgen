#!/usr/bin/env bash
# Apply patches from patches/series onto upstream/ working tree.
#
# Idempotent semantics:
#   - Fresh tree → applies cleanly
#   - Re-run on already-patched tree → resets to HEAD first, then re-applies
#     (so running this twice in a row produces the same result as running once)
#
# Failure semantics:
#   - Any patch fails to apply → print which patch + the offending hunk,
#     exit non-zero, leave the tree in whatever partial state it's in so
#     a developer can inspect with `git -C upstream diff`.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UPSTREAM_DIR="$REPO_ROOT/upstream"
PATCHES_DIR="$REPO_ROOT/patches"
SERIES_FILE="$PATCHES_DIR/series"

if [[ ! -d "$UPSTREAM_DIR/.git" ]] && [[ ! -f "$UPSTREAM_DIR/.git" ]]; then
  echo "error: upstream/ submodule not initialised. Run:" >&2
  echo "  git submodule update --init --recursive" >&2
  exit 2
fi

if [[ ! -f "$SERIES_FILE" ]]; then
  echo "error: patches/series not found at $SERIES_FILE" >&2
  exit 2
fi

# The REAL pin is the submodule gitlink -- that is what a fresh clone and CI
# check out. scripts/upstream.pin is documentation beside it.
#
# Those two can disagree, and when they do this script still passes locally
# while CI fails: locally the submodule is left checked out wherever you were
# working, so patches apply against that, whereas CI takes the gitlink. Porting
# onto upstream 2026.08.1 hit exactly this - upstream.pin was updated, the
# gitlink was not, and "apply + validate" went green here and red in CI.
#
# Fail loudly on the mismatch instead of letting the two drift apart silently.
PIN_FILE="$REPO_ROOT/scripts/upstream.pin"
if [[ -f "$PIN_FILE" ]]; then
  want_pin="$(tr -d '[:space:]' < "$PIN_FILE")"
  # Read the INDEX, not HEAD: the index is what the next commit will carry, so
  # a staged submodule bump satisfies the check while a forgotten one still
  # trips it. Reading HEAD would keep failing after `git add upstream`.
  have_link="$(git -C "$REPO_ROOT" ls-files -s upstream | awk '{print $2}')"
  if [[ -n "$want_pin" && -n "$have_link" && "$want_pin" != "$have_link" ]]; then
    echo "error: upstream pin mismatch." >&2
    echo "  scripts/upstream.pin : $want_pin" >&2
    echo "  submodule gitlink    : $have_link   <-- this is what CI checks out" >&2
    echo "Commit the submodule bump as well:  git add upstream" >&2
    exit 5
  fi
fi

# Reset upstream to the pinned commit so applying patches is deterministic.
cd "$UPSTREAM_DIR"
git reset --hard HEAD --quiet
cd "$REPO_ROOT"

applied=0
while IFS= read -r line || [[ -n "$line" ]]; do
  # Skip comments and blank lines.
  [[ "$line" =~ ^[[:space:]]*# ]] && continue
  [[ -z "${line// }" ]] && continue

  patch_file="$PATCHES_DIR/$line"
  if [[ ! -f "$patch_file" ]]; then
    echo "error: patch file not found: $patch_file (referenced in series)" >&2
    exit 3
  fi

  printf "  applying %s ... " "$line"
  if ! git -C "$UPSTREAM_DIR" apply --index "$patch_file" 2> /tmp/subarr-subgen-patch-err; then
    echo "FAILED"
    echo "---" >&2
    cat /tmp/subarr-subgen-patch-err >&2
    echo "---" >&2
    echo "patch failed: $line" >&2
    echo "inspect with: git -C upstream diff" >&2
    exit 4
  fi
  echo "ok"
  applied=$((applied + 1))
done < "$SERIES_FILE"

echo
echo "applied $applied patch(es) cleanly."
