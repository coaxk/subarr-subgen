# Upstream sync

How we stay current with McCloudS/subgen.

## Why upstream isn't tagged

McCloudS/subgen doesn't publish git tags or GitHub Releases. The
`subgen_version` constant inside `subgen.py` is bumped by a GitHub Action
on every merge to `main`. We pin by **commit SHA**, recorded in
`scripts/upstream.pin` (also as the submodule SHA).

The version constant gives us a human-readable label for releases
(`2026.05.3-r1`); the SHA gives us byte-exact reproducibility.

## How the weekly rebase-test works

Every Monday at 06:00 UTC, `.github/workflows/rebase-test.yml` runs:

1. Clones upstream's `main` HEAD (a fresh clone — does NOT use our pinned
   submodule)
2. Runs `scripts/apply-patches.sh` against that fresh tree
3. Runs `scripts/validate-patched.py`
4. Compares `UPSTREAM_HEAD` against `scripts/upstream.pin`

Three outcomes:

| Apply | Validate | New HEAD? | Outcome |
|---|---|---|---|
| ✓ | ✓ | yes | Opens `Upstream bump available` issue (low priority) |
| ✓ | ✓ | no | Silent success |
| ✗ | — | yes/no | Opens `Upstream drift broke patches` issue (blocking) |
| ✓ | ✗ | yes/no | Opens `Upstream drift broke patches` issue (blocking) |

The blocking-issue path uses a sticky title pattern so we don't accumulate
duplicate issues — it gets updated week-over-week with the latest state.

## Routine bump (clean apply)

1. The bot opens an issue: `Upstream bump available: <short-sha>`
2. Reproduce locally:
   ```bash
   cd upstream && git fetch origin && git checkout origin/main
   git rev-parse HEAD     # confirm matches the issue
   cd ..
   bash scripts/apply-patches.sh
   python scripts/validate-patched.py
   ```
3. If green, update the pin:
   ```bash
   cd upstream && git checkout <sha> && cd ..
   echo "<sha>" > scripts/upstream.pin
   git add upstream scripts/upstream.pin
   ```
4. Read `upstream/subgen.py` for the new `subgen_version` constant
5. Tag and push:
   ```bash
   git commit -m "bump: upstream → <sha> (subgen <new-version>)"
   git tag "v<new-version>-r1"
   git push origin main --tags
   ```
6. Release workflow takes over: builds + pushes + creates GH release
7. Close the bot's issue

Target latency: within 7 days of the bot finding a clean bump.

## Drift bump (patches break)

1. The bot opens an issue: `Upstream drift broke patches (HEAD=<short-sha>)`
2. Reproduce locally:
   ```bash
   cd upstream && git fetch origin && git checkout origin/main && cd ..
   bash scripts/apply-patches.sh
   ```
3. Identify the failing patch from the error output
4. Inspect the conflict — look at upstream's current code around the
   patch's anchor lines
5. Choose a fix path:

   **Path A — mechanical port** (line numbers moved but logic intact):
   - Try `git -C upstream apply --3way patches/<failing>.patch`
   - If that lands, regenerate the patch:
     ```bash
     cd upstream
     git commit -am "regenerate: <patch-name>"
     git format-patch -1 --no-signature --zero-commit -o ../patches/
     # rename to canonical filename
     ```

   **Path B — semantic port** (upstream restructured):
   - Edit `upstream/subgen.py` to apply our intent against the new structure
   - Commit + format-patch + rename
   - Update validator if the structural contract changed

   **Path C — drop the patch** (upstream now does this natively):
   - Best outcome. Open subarr issue to migrate the client to the new
     upstream shape.
   - Remove patch from `patches/series` and delete the `.patch` file
   - Update `RELEASES.md` next-release notes

6. Validate the full stack: `python scripts/validate-patched.py`
7. Bump + tag + release as in the routine path
8. Close the bot's issue, link to your fix

## Major-version bumps

If upstream cuts a `subgen_version` that crosses a major boundary (e.g.
2026 → 2027), or restructures pervasively, expect non-trivial drift.

Coping strategies:
- Triage the bump on a branch, not main
- Stand up a `compat-<old-version>` branch from pre-bump main; users who
  can't migrate immediately pin to that branch's released tags
- Communicate the bump on the subarr repo (the orchestrator usually has
  client-side shape assumptions we'll need to update in lockstep)
