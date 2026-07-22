#!/usr/bin/env python3
"""Fix dependabot's stale action version comments, without losing suppressions.

THE PROBLEM
-----------
Dependabot bumps a pinned action's SHA but frequently writes the wrong version
comment beside it -- e.g. it moved softprops/action-gh-release to v3.0.2's
commit while labelling it `# v3.0.1`. zizmor's `ref-version-mismatch` (an ONLINE
audit, so it needs a GitHub token) catches that and reds CI on essentially every
actions-group bump.

THE TRAP THIS SCRIPT EXISTS FOR
-------------------------------
The obvious fix is `zizmor --fix=unsafe-only`, and it works -- but it also
STRIPS `# zizmor: ignore[...]` suppression comments from the lines it rewrites.
That has happened twice (coaxk/subarr#427, and again here on
softprops/action-gh-release). A stripped suppression is silent: CI goes green,
nothing surfaces it, and the next run of that audit fails for a different reason
that looks unrelated.

So: run the auto-fix, then put the suppressions back, and refuse to accept the
result if any pinned SHA actually moved -- a comment fix must never quietly
become a supply-chain change.

USAGE
-----
    GH_TOKEN=$(gh auth token) python scripts/fix-action-pins.py [workflows_dir]

Exit codes:
    0  workflows already clean, or fixed successfully (review + commit the diff)
    1  a pinned SHA changed, or zizmor still reports findings -- needs a human
    2  environment problem (zizmor missing, no token, no workflows)
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

# `uses: owner/repo@<40-hex>` -- the pin we care about.
USES_RE = re.compile(r"uses:\s*(?P<action>[^@\s]+)@(?P<sha>[0-9a-f]{40})")
SUPPRESSION_RE = re.compile(r"#\s*zizmor:\s*ignore\[[^\]]+\]")


def read_all(workflows: Path) -> dict[Path, str]:
    files = sorted(list(workflows.glob("*.yml")) + list(workflows.glob("*.yaml")))
    return {p: p.read_text(encoding="utf-8") for p in files}


def pins(text: str) -> set[tuple[str, str]]:
    """(action, sha) pairs. Comment-only fixes leave this set identical."""
    return {(m.group("action"), m.group("sha")) for m in USES_RE.finditer(text)}


def suppressions(text: str) -> dict[str, str]:
    """sha -> suppression comment, for pin lines that carry one."""
    found: dict[str, str] = {}
    for line in text.splitlines():
        pin = USES_RE.search(line)
        sup = SUPPRESSION_RE.search(line)
        if pin and sup:
            found[pin.group("sha")] = sup.group(0)
    return found


def restore_suppressions(text: str, wanted: dict[str, str]) -> tuple[str, list[str]]:
    """Re-append any suppression the auto-fix dropped. Matches on the SHA, which
    is stable across a comment-only fix."""
    restored: list[str] = []
    out = []
    for line in text.splitlines(keepends=True):
        pin = USES_RE.search(line)
        if pin:
            sha = pin.group("sha")
            if sha in wanted and not SUPPRESSION_RE.search(line):
                stripped = line.rstrip("\r\n")
                ending = line[len(stripped) :]
                line = f"{stripped} {wanted[sha]}{ending}"
                restored.append(f"{pin.group('action')}@{sha[:12]}")
        out.append(line)
    return "".join(out), restored


def run_zizmor(workflows: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["zizmor", *extra, str(workflows)],
        capture_output=True,
        text=True,
    )


def main(argv: list[str]) -> int:
    workflows = Path(argv[1] if len(argv) > 1 else ".github/workflows")
    if not workflows.is_dir():
        print(f"error: {workflows} is not a directory", file=sys.stderr)
        return 2

    before = read_all(workflows)
    if not before:
        print(f"error: no workflow files in {workflows}", file=sys.stderr)
        return 2

    if not (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")):
        print(
            "error: ref-version-mismatch is an ONLINE audit and needs a token.\n"
            "       Re-run with:  GH_TOKEN=$(gh auth token) python "
            f"{Path(__file__).as_posix()}",
            file=sys.stderr,
        )
        return 2

    probe = run_zizmor(workflows)
    if "No findings to report" in (probe.stdout + probe.stderr):
        print("already clean -- nothing to fix.")
        return 0

    print("findings present; running the auto-fix...")
    run_zizmor(workflows, "--fix=unsafe-only")
    after = read_all(workflows)

    # A comment fix must never move a pin. If one did, this is not the cosmetic
    # change we signed up for -- put everything back and let a human look.
    moved: list[str] = []
    for path, old in before.items():
        new = after.get(path, "")
        for action, sha in sorted(pins(old) - pins(new)):
            moved.append(f"  {path.name}: {action}@{sha[:12]} is no longer pinned")
    if moved:
        for path, old in before.items():
            path.write_text(old, encoding="utf-8", newline="")
        print(
            "REFUSED: the auto-fix changed a pinned SHA, not just a comment.\n"
            + "\n".join(moved)
            + "\n\nAll workflow files were restored. Inspect by hand before pinning anything new.",
            file=sys.stderr,
        )
        return 1

    # Put back any suppression the fix ate.
    all_restored: list[str] = []
    for path, old in before.items():
        new = after.get(path, "")
        fixed, restored = restore_suppressions(new, suppressions(old))
        if fixed != new:
            path.write_text(fixed, encoding="utf-8", newline="")
        for item in restored:
            all_restored.append(f"  {path.name}: {item}")

    changed = [
        p.name for p, old in before.items() if p.read_text(encoding="utf-8") != old
    ]
    if all_restored:
        print("restored suppressions the auto-fix stripped:")
        print("\n".join(all_restored))
    print(f"comment fixes applied to: {', '.join(changed) if changed else '(none)'}")

    final = run_zizmor(workflows)
    if "No findings to report" not in (final.stdout + final.stderr):
        print(
            "\nzizmor still reports findings after the fix -- these are not the "
            "dependabot comment drift and need a human:\n",
            file=sys.stderr,
        )
        print(final.stdout or final.stderr, file=sys.stderr)
        return 1

    print("zizmor clean. Review `git diff` (expect comment-only changes) and commit.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
