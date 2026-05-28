# Developing a new patch

How to add a patch to the stack.

## When to add a patch

Add a patch when subarr needs a capability upstream subgen doesn't provide,
and it's worth maintaining the divergence. Default answer is **don't add a
patch** — every patch is a maintenance liability when upstream changes.

Good reasons:
- subarr depends on a new endpoint shape upstream won't accept
- a critical bug fix upstream hasn't merged yet
- a structural feature upstream is unlikely to merge (e.g. our `/batch`
  shape, which is opinionated about scan_id semantics)

Bad reasons:
- "I'd find this nicer" (subjective — open an upstream PR)
- "subgen could be faster here" (file an upstream issue)
- "I want this configurable" (use env vars)

## Workflow

1. Branch the repo:
   ```bash
   git checkout -b add-patch-NNNN-description
   ```

2. Apply existing patches to get a working upstream tree:
   ```bash
   bash scripts/apply-patches.sh
   ```

3. Develop your change directly in `upstream/subgen.py` (the submodule).
   Test interactively if needed.

4. Commit inside the submodule:
   ```bash
   cd upstream
   git -c user.email=subarr@localhost -c user.name="subarr-subgen" \
     commit -am "NNNN: short description

   Longer explanation: why this patch exists, what subarr depends on,
   any non-obvious design choices."
   ```

5. Generate the `.patch` file:
   ```bash
   git -C upstream format-patch -1 --no-signature --zero-commit \
     -o ../patches/
   ```

   This produces `patches/NNNN-<commit-subject-slug>.patch`. Rename it to
   your canonical filename (e.g. `0008-my-new-thing.patch`).

6. Add to the series in order:
   ```bash
   echo "0008-my-new-thing.patch" >> patches/series
   ```

7. Reset the submodule (so we're back at the vanilla pin):
   ```bash
   cd upstream
   git reset --hard HEAD~1
   cd ..
   ```

8. Test the full stack applies cleanly:
   ```bash
   bash scripts/apply-patches.sh
   python scripts/validate-patched.py
   ```

9. Add validator checks for your patch in `scripts/validate-patched.py`
   if it has a testable structural contract (e.g. a new endpoint, a new
   function signature).

10. Test the docker build:
    ```bash
    bash scripts/build.sh
    ```

11. Commit + PR.

## Patch ordering

The series file is applied top-to-bottom. Order matters when patches touch
overlapping line regions. General rule:

- Most isolated patches first
- Patches that depend on context introduced by earlier patches go later
- Full-unit function replacements early (less context-sensitive than line
  hunks)

If reordering an existing patch breaks earlier ones, the `apply-patches.sh`
will catch it loudly. Trust the failure, don't paper over it.

## When upstream restructures

If a new upstream release breaks your patch:

- The weekly rebase-test will open an issue
- Follow the recipe in `docs/upstream-sync.md`
- If the change is mechanical (line numbers moved), patches often re-apply
  with `git apply --3way`. Try that first.
- If the change is structural (function signature changed, file split),
  port the patch by hand against the new upstream tree, regenerate the
  `.patch` file, commit.

## Validator coverage

Every patch should have at least one assertion in
`scripts/validate-patched.py` that proves it landed. Text-match is fine
for simple cases ("our marker comment is present"); AST is better for
function-shape contracts ("function X has arg Y").

Don't trust apply-clean as proof of correctness — a patch can apply
textually while corrupting semantics. The validator's compile + AST gates
exist because v2/v3 of the original patcher shipped broken Python that
"applied clean." We don't make that mistake twice.
