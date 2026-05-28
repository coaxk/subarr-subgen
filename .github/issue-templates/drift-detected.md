## Upstream drift broke our patches

Weekly rebase-test ran against upstream `main` HEAD and either:
- a patch failed to apply (apply-patches.sh exited non-zero), or
- patches applied but the validator failed (structural contract violated)

Need to manually port. See the workflow run logs for which patch broke and
what the conflicting hunks look like.

### Diagnostic steps

1. Pull this repo locally + check out main
2. Reset the upstream submodule to upstream's current HEAD (not our pin):
   ```bash
   cd upstream
   git fetch origin
   git checkout origin/main
   cd ..
   ```
3. Run `bash scripts/apply-patches.sh` to see which patch fails first
4. Inspect the conflict: `git -C upstream diff` shows partial-apply state if any
5. For each failing patch:
   - Open the `.patch` file in `patches/`
   - Find the hunk that didn't apply
   - Locate the new upstream code at the failure site
   - Port the patch by hand (or regenerate via the extraction helper if the
     change is mechanical)
6. Test: `bash scripts/apply-patches.sh && python scripts/validate-patched.py`
7. Commit the updated patch(es) + the new upstream submodule SHA + bump
   `scripts/upstream.pin`

### If upstream restructured deeply

Sometimes a patch can't be cleanly ported (e.g. upstream renamed a function
we patch). Options:

- **Drop the patch** if upstream now provides the feature natively (good
  outcome — open a subarr issue to switch our client to the new shape)
- **Rewrite the patch** against the new upstream structure
- **Pin to last-known-good upstream** and ship a `compat-2026.05` branch
  while we port

### Don't bypass

Do NOT silently skip a failing patch or relax the validator. The validator
gates exist because patch corruption shipped silently in v2/v3 (the
`update_subgen_v4.py` header documents this lesson). If it fails, we fix it
before the next release.
