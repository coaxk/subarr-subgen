# Tagging scheme

Image tags follow **`<upstream_version>-r<patch_rev>`**.

- `<upstream_version>` — the value of `subgen_version` constant inside
  upstream's `subgen.py` at our pinned commit. With leading `v` stripped.
  Example: `2026.05.3`.
- `<patch_rev>` — monotonic integer. Increments when **our patches change**
  without an upstream bump. Resets to `1` when upstream is bumped.

Git tags mirror image tags exactly: `v2026.05.3-r1`.

## Moving tags published alongside each release

| Tag | Semantics | Updated when |
|---|---|---|
| `<upstream>-r<rev>` | Immutable — points at one specific build | Never moves |
| `<upstream>` | Latest `-r*` for this upstream pin | Every release that targets this upstream |
| `latest` | Newest release, regardless of stability | Every release |
| `stable` | Manually promoted; safe for non-power-users | Manually, after ≥7 days in `latest` with no reported regression |
| `dev` | `main` branch HEAD builds | Every `push` to `main` (not PRs) |

## Production guidance

**Always pin to `<upstream>-r<rev>` in production.** Never use `:latest` or
`:stable` in a compose file you care about; both can move under you.

If you want auto-tracking, use `<upstream>` and accept that patch-rev
bumps (security fixes, validator improvements) will land automatically.

## Examples

```yaml
# Recommended: pin exactly
image: ghcr.io/coaxk/subarr-subgen:2026.05.3-r1

# Track patch-rev within this upstream
image: ghcr.io/coaxk/subarr-subgen:2026.05.3

# Yolo — don't do this in production
image: ghcr.io/coaxk/subarr-subgen:latest
```

## Bumping upstream

When we bump the submodule pin:

```bash
cd upstream
git fetch origin
git checkout <new-sha>
cd ..
echo "<new-sha>" > scripts/upstream.pin
git add upstream scripts/upstream.pin
git commit -m "bump: upstream → <new-sha> (subgen <new-version>)"
git tag "v<new-version>-r1"
git push origin main --tags
```

The release workflow takes over from there.

## Yanking a bad release

We never delete GHCR tags. If a release ships a regression:

1. Edit `RELEASES.md`: change the row's `status` to `yanked`, add notes
2. Repoint `:stable` to the previous known-good (manual workflow_dispatch
   on a forthcoming `promote-stable.yml`)
3. Edit the GitHub release for the yanked tag, add a `**⚠ YANKED**` banner
   pointing at the replacement
4. Cut a fixforward release (`-r<N+1>`) with the regression fixed
