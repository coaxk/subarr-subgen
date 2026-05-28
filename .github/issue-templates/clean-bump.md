## Upstream bump available — no patch conflicts

Our weekly rebase-test found a newer upstream commit on McCloudS/subgen `main`,
and our patches still apply cleanly + the validator still passes. Suggesting a
routine bump.

- **Current pin**: see `scripts/upstream.pin`
- **Upstream HEAD**: see workflow run env (`UPSTREAM_HEAD`)
- **Status**: green — apply + validate succeeded

### How to bump

```bash
cd upstream
git fetch origin
git checkout <new-sha>
cd ..
echo <new-sha> > scripts/upstream.pin
git add upstream scripts/upstream.pin
git commit -m "bump: upstream → <new-sha>"
```

Then cut a release: tag `v<upstream-version>-r1` and push the tag.

If upstream's `subgen_version` constant didn't change, increment the patch
rev instead: `v<same-upstream-version>-r<N+1>`.

This issue can be closed after the bump lands.
