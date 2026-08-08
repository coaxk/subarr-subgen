#!/usr/bin/env bash
# Build phase 2 arms 1 and 2 from PRISTINE upstream trees.
#
# Same Dockerfile, same CUDA base, same requirements as arm 3 -- only subgen.py
# differs. Building arms 1/2 from a different Dockerfile would let base image or
# dependency drift masquerade as a segmenter difference, which is the one thing
# this study must not confuse.
#
# NO patches are applied. That is the point of arms 1 and 2.
#
# ⚠️ Both refs are EXPLICIT SHAs, never FETCH_HEAD. An earlier version used
# FETCH_HEAD for arm 2 and the branch moved mid-build (upstream shipped the
# fw_kwargs fix from McCloudS/subgen#355), leaving it genuinely ambiguous which
# commit got staged. A study arm you cannot name the commit for is not evidence.
set -euo pipefail

REPO=/mnt/c/Projects/subarr-subgen
DOCKERFILE="$REPO/docker/Dockerfile"

ARM1_REF=f38dcaa8cd287556faaa2f7ea45e708096f19e67   # upstream main @ 2026.07.3 (our pin)
ARM2_REF=7d43d9a                                     # refactor/drop-stable-ts, incl. the #355 fix

build_arm () {
  local name="$1" ref="$2" version="$3"
  local ctx="/tmp/phase2-$name"

  echo "=== $name : staging pristine tree at $ref ==="
  rm -rf "$ctx"; mkdir -p "$ctx"
  git -C "$REPO/upstream" archive "$ref" | tar -x -C "$ctx"

  # Prove no patch leaked in: every one of our patches stamps subgen.py with the
  # capabilities dict or a subarr marker.
  if grep -q 'subarr_subgen_patch_rev\|"capabilities"' "$ctx/subgen.py"; then
    echo "FATAL: $name context looks PATCHED -- refusing to build a mislabelled arm." >&2
    exit 2
  fi
  local want
  want=$(git -C "$REPO/upstream" rev-parse "$ref:subgen.py")
  echo "  unpatched: no subarr markers"
  echo "  subgen.py blob: $want"

  echo "=== $name : docker build ==="
  docker build -q \
    -f "$DOCKERFILE" \
    --build-arg UPSTREAM_VERSION="$version" \
    --build-arg PATCH_REV="none-unpatched" \
    --build-arg RELEASE_TAG="phase2-$name" \
    -t "phase2-$name:latest" \
    "$ctx" > /dev/null

  # Verify the IMAGE carries the source we think it does. A green build is not
  # proof the right tree went in -- check the artifact, not the workflow.
  local got
  got=$(docker run --rm --entrypoint sh "phase2-$name:latest" -c 'git hash-object /subgen/subgen.py 2>/dev/null || python3 -c "
import hashlib,sys
d=open(\"/subgen/subgen.py\",\"rb\").read()
sys.stdout.write(hashlib.sha1(b\"blob %d\\0\" % len(d)+d).hexdigest())
"')
  if [ "$got" != "$want" ]; then
    echo "FATAL: $name image subgen.py is $got, expected $want" >&2
    exit 3
  fi
  echo "=== $name : built and VERIFIED (image blob matches $ref) ==="
  rm -rf "$ctx"
}

# Optional arg selects a single arm; no arg builds both. An arm whose image
# already exists is skipped -- each is ~20 GB and rebuilding one needlessly is
# a long wait for nothing.
ONLY="${1:-}"

maybe_build () {
  local name="$1" ref="$2" version="$3"
  if [ -n "$ONLY" ] && [ "$ONLY" != "$name" ]; then
    echo "=== $name : not selected, skipping ==="
    return 0
  fi
  if docker image inspect "phase2-$name:latest" > /dev/null 2>&1; then
    echo "=== $name : image already present, skipping build ==="
    return 0
  fi
  build_arm "$name" "$ref" "$version"
}

maybe_build arm1 "$ARM1_REF" "2026.07.3"
maybe_build arm2 "$ARM2_REF" "drop-stable-ts-7d43d9a"

echo
docker images --format '{{.Repository}}:{{.Tag}}  {{.Size}}' | grep phase2- || true
