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
