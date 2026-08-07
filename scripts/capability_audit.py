# scripts/capability_audit.py
"""#171 Phase 1: does every capability we depend on have a seam on
refactor/drop-stable-ts?

A patch conflicting is uninteresting -- context drift is routine sync work. A
capability whose SEAM is gone cannot be re-ported at any price, and that is the
veto. See docs/superpowers/specs/2026-08-04-171-drop-stable-ts-evidence-design.md
in the subarr repo.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from collections import Counter
from enum import StrEnum
from pathlib import Path
from typing import NamedTuple

# Matches any quoted snake_case key followed by a colon on an added line --
# not just entries inside the /queue capabilities dict. The value may be
# True, an int, or an expression -- concurrent_transcriptions is an int -- so the
# value side is deliberately not constrained. Callers must filter the result
# against ADVERTISED_CAPABILITIES; see capabilities_added_by_patch below.
_CAP_ENTRY = re.compile(r'"(?P<name>[a-z][a-z0-9_]*)"\s*:')


def capabilities_added_by_patch(patch_text: str) -> set[str]:
    """Capability names this patch ADDS.

    Only `+` lines count. Patch context lines show neighbouring flags, and
    attributing those to the patch credits the wrong one -- verified during
    planning, where a naive scan credited 0010-queue-cancel with
    audio_language_override, which it merely sits below.

    This matches any quoted snake_case key followed by a colon on an added
    line, not just entries inside the capabilities dict -- it over-matches by
    design, so callers must filter the result against the known capability
    set rather than trusting it directly.
    """
    found: set[str] = set()
    for line in patch_text.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        for m in _CAP_ENTRY.finditer(line):
            found.add(m.group("name"))
    return found


# The 16 flags a live patched subgen advertises under /queue -> capabilities.
# Captured 2026-08-04 from the running 2026.07.3-r1 image. This is the contract
# subarr negotiates against; anything else on an added line is a response field,
# not a capability.
#
# There is a 17th audit-worthy capability, CUSTOM_REGROUP, which advertises no
# flag at all -- patches 0001 and 0017 set it via `args['regroup'] = ...`, a
# dict assignment this file's regex never matches by design. It is handled by
# hand, not in this set.
#
# The test suite guards this set against DRIFT (a listed capability losing its
# only patch provider) but not against GAPS: a brand-new capability a patch
# adds that never gets added here. That direction still needs a human to
# recapture the list from a live image.
ADVERTISED_CAPABILITIES = frozenset(
    {
        "asr_arena",
        "asr_detected_language",
        "asr_vanilla_base",
        "async_config",
        "audio_language_override",
        "concurrent_transcriptions",
        "curated_language_prompts",
        "detect_language_track",
        "ignore_forced_subtitles",
        "per_request_kwargs",
        "per_request_task",
        "queue_cancel",
        "request_ignore_forced",
        "robust_language_detection",
        "runtime_config",
        "safe_decode_preset",
    }
)


def build_capability_map(patches: dict[str, str]) -> dict[str, list[str]]:
    """capability -> sorted list of patch filenames that add it.

    ``patches`` maps patch filename to its text. Capabilities not in
    ADVERTISED_CAPABILITIES are dropped: they are response fields, not contract.
    """
    out: dict[str, list[str]] = {}
    for name in sorted(patches):
        for cap in capabilities_added_by_patch(patches[name]):
            if cap in ADVERTISED_CAPABILITIES:
                out.setdefault(cap, []).append(name)
    return out


# `@@ -a,b +c,d @@ <context>` -- git puts the NEAREST PRECEDING COLUMN-0 LINE in
# <context>. upstream/ has no .gitattributes, so git falls back to its default
# funcname heuristic (not the Python driver), which does not know a def body
# from a module-level statement -- it just walks up to the last line starting
# in column 0. Proof: real headers in patches/ carry contexts like
# `subgen_version = '2026.06.4'`, `import requests`, and `try:`.
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@\s*(?P<ctx>.*)$")
_SYMBOL = re.compile(r"^(?:async\s+)?(?:def|class)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)")


def seams_for_patch(patch_text: str) -> set[str]:
    """Hunk-header context names that look like a def/class signature.

    These are NOT guaranteed upstream symbols. A hunk can attach to a
    function/class our OWN earlier patch created, and it will still show up
    here -- 4 of the seams this file extracts across patches/ (queue_status,
    runtime_config, detect_language_robust, detect_language_robust_task) do
    not exist in the pinned upstream base at all; queue_status is DEFINED by
    0007-deduplicated-queue-type-tracking-and-queue-endpoint.patch. Callers
    MUST intersect this function's output against the pinned base's real
    symbol table before asking whether a branch still has them -- skipping
    that step already produced one spurious veto, on runtime_config.

    These are also NOT guaranteed attachment points, for the same funcname-
    heuristic reason documented on _HUNK above: git reports the nearest
    preceding column-0 line, which is not necessarily where the hunk's added
    code actually lands. Concretely, 0007's queue-endpoint hunk carries the
    header `@@ ... @@ def webui():`, but the diff context shows it sits right
    below `def status():` and adds a brand-new `queue_status`, touching
    neither webui nor status. webui, path_mapping, send_completion_webhook,
    get_audio_languages, and subtitle_exists_in_language are real upstream
    functions that never once have added code land inside their body across
    the whole patch set -- every hunk naming them is this same proximity
    artifact.

    Finally, a seam name surviving unchanged on a branch is not evidence the
    attachment survived: `args.update(kwargs)` appears 3 times in the pinned
    base (inside asr_task_worker, detect_language_from_upload, gen_subtitles)
    and 0 times on refactor/drop-stable-ts, while all three enclosing function
    names are still present there. The name is not the seam; the code at the
    name is the seam, and this function cannot see that far.

    A hunk whose header's nearest column-0 line is not a def or class --
    e.g. `subgen_version = '2026.06.4'`, `import requests`, `try:`, or a hunk
    at the very top of the file with no preceding line at all -- contributes
    no seam. That is 28 of 129 real hunk headers, 26 of them a module-level
    statement rather than the file-top case; treat an empty return as "no
    evidence found", not as "this patch is safely self-contained".
    """
    seams: set[str] = set()
    for line in patch_text.splitlines():
        m = _HUNK.match(line)
        if not m:
            continue
        sym = _SYMBOL.match(m.group("ctx").strip())
        if sym:
            seams.add(sym.group("name"))
    return seams


# A hunk header declares how many lines it covers on each side. Parsing those
# counts is what lets us bound the body exactly, instead of guessing that the
# body ends at the next line that happens to look like a header -- a removed
# line beginning "--" renders as "---" and would fool a naive boundary scan.
# Both counts are optional: `@@ -5 +5 @@` means one line each side.
_HUNK_COUNTS = re.compile(r"^@@ -\d+(?:,(?P<old>\d+))? \+\d+(?:,(?P<new>\d+))? @@")


class Hunk(NamedTuple):
    """One individually-appliable hunk, with enough provenance to report it."""

    patch: str  # patch filename it came from
    file: str  # target path, e.g. "subgen.py"
    header: str  # the @@ line, newline-terminated
    body: str  # the hunk body, newline-terminated


def hunks_of(patch_name: str, patch_text: str) -> list[Hunk]:
    """Split a patch into hunks that can each be applied on their own.

    Tracks the target file from `+++ b/<path>` so a multi-file patch does not
    attribute hunks to the wrong file -- 0021 touches entrypoint.sh, and
    probing that against subgen.py would be a category error.
    """
    hunks: list[Hunk] = []
    cur_file = ""
    lines = patch_text.splitlines(keepends=True)
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("+++ "):
            cur_file = line[4:].strip()
            if cur_file.startswith("b/"):
                cur_file = cur_file[2:]
            i += 1
            continue
        m = _HUNK_COUNTS.match(line)
        if not m:
            i += 1
            continue
        old_left = int(m.group("old")) if m.group("old") is not None else 1
        new_left = int(m.group("new")) if m.group("new") is not None else 1
        body: list[str] = []
        i += 1
        while i < len(lines) and (old_left > 0 or new_left > 0):
            b = lines[i]
            # A genuine next hunk header always starts at column 0 with "@@" --
            # every real body line starts with " ", "+", "-", or "\" instead, so
            # this can never misfire on content. It is the backstop for a hunk
            # whose declared counts overrun its actual body (fuzzy/hand-edited
            # patches): without it, unresolved counts would walk straight
            # through the next hunk's header and swallow it as bogus context.
            #
            # This backstop does NOT catch an overrun into a "--- a/<file>" /
            # "+++ b/<file>" pair -- those start with "-"/"+" and get consumed
            # as ordinary content lines, so in a multi-file patch the following
            # hunks would be mis-attributed to the wrong target file. Not
            # handled: all 129 hunks in patches/ have exact counts (confirmed
            # by the 129-hunk, correctly-per-file real-patch run), so this
            # cannot happen on our current patch stack.
            if _HUNK_COUNTS.match(b):
                break
            if b.startswith("\\"):  # "\ No newline at end of file"
                body.append(b)
                i += 1
                continue
            if b.startswith("-"):
                old_left -= 1
            elif b.startswith("+"):
                new_left -= 1
            else:  # context line counts against both sides
                old_left -= 1
                new_left -= 1
            body.append(b)
            i += 1
        hunks.append(Hunk(patch_name, cur_file, line, "".join(body)))
    return hunks


def hunk_as_patch(h: Hunk) -> str:
    """Reconstruct a standalone patch `git apply` will accept for one hunk."""
    return f"--- a/{h.file}\n+++ b/{h.file}\n{h.header}{h.body}"


# ---------------------------------------------------------------------------
# The probe. THIS is the verdict; seams_for_patch above is a triage index only.
#
# An earlier design compared upstream symbol NAMES between base and branch. It
# was scrapped because it cannot fire: of the upstream symbols our patches
# attach to, refactor/drop-stable-ts removes exactly ZERO, so a name-matcher
# emits all-green by construction. Meanwhile `args.update(kwargs)` -- the
# actual attachment point for the per-request kwargs family -- went from 3
# occurrences to 0 while all three enclosing function names survived intact.
# The name is not the seam. Applying the hunk is the only honest test, because
# it asks the branch about the CODE our patch lands on, not its label.
# ---------------------------------------------------------------------------

# The only upstream file this branch refactors, and so the only one materialised.
# patches/0021 also touches entrypoint.sh; probing that against a subgen.py-only
# tree would be a category error, so those hunks are reported as
# SKIPPED_OTHER_FILE rather than silently dropped from the denominator.
PROBED_FILE = "subgen.py"

# BASE_REF is the commit upstream/ is pinned to -- read from the submodule's own
# HEAD, which scripts/upstream.pin records. Note this reads COMMITTED blobs, so
# uncommitted changes in the upstream/ working tree cannot contaminate the run.
BASE_REF = "HEAD"

# FETCH_HEAD is what `git fetch origin refactor/drop-stable-ts` leaves behind and
# is the documented invocation. It is also volatile -- any later unrelated fetch
# in upstream/ overwrites it -- so fall back to the remote-tracking ref, which
# names the same branch but survives. The resolved SHA is printed in the report
# header so a reader can always confirm which tree was actually probed.
BRANCH_REFS = ("FETCH_HEAD", "origin/refactor/drop-stable-ts")


class HunkOutcome(StrEnum):
    INTACT = "INTACT"
    BROKEN_BY_BRANCH = "BROKEN_BY_BRANCH"
    INCONCLUSIVE = "INCONCLUSIVE"
    SKIPPED_OTHER_FILE = "SKIPPED_OTHER_FILE"


# Fixed display order: the two decisive outcomes first, then the two that are
# absences of evidence rather than evidence.
_OUTCOME_ORDER = (
    HunkOutcome.INTACT,
    HunkOutcome.BROKEN_BY_BRANCH,
    HunkOutcome.INCONCLUSIVE,
    HunkOutcome.SKIPPED_OTHER_FILE,
)


def classify_hunk(applies_base: bool, applies_branch: bool) -> HunkOutcome:
    """Turn a pair of `git apply --check` results into a verdict.

    Failing on the pinned BASE is not evidence about the branch in either
    direction -- it means the probe cannot read this hunk standalone, because
    it lands on text an EARLIER patch in the stack creates. So both branch
    answers collapse to INCONCLUSIVE, deliberately: scoring them broken would
    invent damage, and scoring them intact would hide it.
    """
    if not applies_base:
        return HunkOutcome.INCONCLUSIVE
    return HunkOutcome.INTACT if applies_branch else HunkOutcome.BROKEN_BY_BRANCH


def _git(repo: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True
    ).stdout


def _materialise(upstream: Path, ref: str, dest: Path) -> None:
    """Lay down a pristine one-file tree at `ref`, then make it a git repo.

    `cat-file blob`, NOT `show`: `show` runs checkout filters (eol conversion,
    smudge), and a CRLF-converted subgen.py would fail every LF hunk in
    patches/ -- yielding an all-INCONCLUSIVE report that reads like a finding
    instead of like the tooling bug it would be.
    """
    dest.mkdir(parents=True, exist_ok=True)
    blob = _git(upstream, "cat-file", "blob", f"{ref}:{PROBED_FILE}")
    (dest / PROBED_FILE).write_bytes(blob)
    subprocess.run(["git", "init", "-q"], cwd=dest, check=True, capture_output=True)


def _applies(patch_bytes: bytes, tree: Path) -> bool:
    """`git apply --check` one reconstructed hunk against a materialised tree.

    stdin is bytes WE encoded as UTF-8: 19 of the 34 patches carry non-ASCII
    (em-dashes in comments), and letting subprocess encode with the Windows
    console default (cp1252) raises UnicodeEncodeError part-way through a run.

    `git apply` tolerates a line-number OFFSET but not changed context, which is
    exactly the question worth asking: drift is routine, a vanished seam is the
    veto.
    """
    done = subprocess.run(
        ["git", "apply", "--check", "-"],
        cwd=tree,
        input=patch_bytes,
        capture_output=True,
    )
    return done.returncode == 0


def probe_hunk(h: Hunk, base: Path, branch: Path) -> HunkOutcome:
    """Classify one hunk by trying it against both materialised trees."""
    if h.file != PROBED_FILE:
        return HunkOutcome.SKIPPED_OTHER_FILE
    blob = hunk_as_patch(h).encode("utf-8")
    return classify_hunk(_applies(blob, base), _applies(blob, branch))


# (capability, providing patches, counts by outcome, headers of broken hunks)
CapabilityRow = tuple[str, list[str], dict[HunkOutcome, int], list[str]]


def _counts_cell(counts: dict[HunkOutcome, int]) -> str:
    parts = [f"{o.value} {counts[o]}" for o in _OUTCOME_ORDER if counts.get(o)]
    return ", ".join(parts) or "no hunks"


def render_report(
    rows: list[CapabilityRow],
    branch_sha: str,
    *,
    per_patch: dict[str, dict[HunkOutcome, int]] | None = None,
    broken: list[Hunk] | None = None,
    base_sha: str = "",
) -> str:
    """Render the audit as markdown.

    `per_patch` is the whole-stack census -- every hunk in patches/, including
    those in patches that map to no advertised capability. It is optional
    because the capability rows are the contract; it is supplied in real runs
    because the per-capability view alone cannot show the denominator.

    `broken` is every BROKEN_BY_BRANCH hunk stack-wide, and it is not
    redundant with the per-capability rows: those can only name breaks in
    patches that add a capability literal, which on the real stack is 4 of 11.
    The other 7 -- including the args.update(kwargs) triple, the most
    load-bearing break there is -- would otherwise be invisible. That is
    caveat 2 below biting the report itself.
    """
    per_patch = per_patch or {}
    total = Counter()
    for counts in per_patch.values():
        total.update(counts)
    n_hunks = sum(total.values())

    out: list[str] = []
    a = out.append

    a("# refactor/drop-stable-ts: capability audit")
    a("")
    a(
        "Generated by `scripts/capability_audit.py`. Every hunk in `patches/` is "
        "applied against two pristine trees and judged by whether `git apply` "
        "accepts it."
    )
    a("")
    a(f"- **Branch probed**: `refactor/drop-stable-ts` @ `{branch_sha}`")
    if base_sha:
        a(f"- **Pinned base**: `{base_sha}` (the commit `upstream/` sits on)")
    if n_hunks:
        a(f"- **Hunks probed**: {n_hunks} across {len(per_patch)} patches")
        a(f"- **Stack-wide totals**: {_counts_cell(dict(total))}")
    a("")

    a("## Method: apply the hunk, do not match the name")
    a("")
    a(
        "An earlier design compared upstream symbol NAMES between base and "
        "branch. It was scrapped because it could not fire: of the upstream "
        "symbols our patches attach to, this branch removes exactly **zero**, "
        "so a name-matcher emits all-green by construction. Meanwhile "
        "`args.update(kwargs)` -- the real attachment point for the "
        "per-request kwargs family -- went from **3 occurrences to 0** while "
        "all three enclosing function names survived. The name is not the "
        "seam. `seams_for_patch` remains in the module as a triage index and "
        "is **not** the verdict."
    )
    a("")
    a("Each hunk is reconstructed as a standalone patch and offered to both trees:")
    a("")
    a("| Applies to base | Applies to branch | Outcome |")
    a("| --- | --- | --- |")
    a("| yes | yes | `INTACT` -- the code this hunk lands on still exists |")
    a("| yes | no | `BROKEN_BY_BRANCH` -- decisive: the seam is gone |")
    a("| no | either | `INCONCLUSIVE` -- see the caveat below |")
    a("")
    a(
        "`git apply` tolerates a line-number offset but requires the context to "
        "match exactly, so `INTACT` means the surrounding code is still there "
        "verbatim, not merely that a function of the same name is."
    )
    a("")

    a("## Capabilities")
    a("")
    if rows:
        a("| Capability | Providing patches | Outcomes |")
        a("| --- | --- | --- |")
        for cap, providers, counts, _broken in rows:
            provs = ", ".join(f"`{p}`" for p in providers) or "-"
            a(f"| `{cap}` | {provs} | {_counts_cell(counts)} |")
        a("")

        broken_rows = [r for r in rows if r[3]]
        a("### Broken hunks, by capability")
        a("")
        if broken_rows:
            # NB: do NOT bind this loop variable to `broken` -- that is the
            # stack-wide parameter, and shadowing it silently emptied the
            # stack-wide section on the first run of this code.
            for cap, _providers, _counts, headers in broken_rows:
                a(f"**`{cap}`**")
                a("")
                for header in headers:
                    a(f"- `{header}`")
                a("")
        else:
            a("No capability-mapped hunk was decisively broken by the branch.")
            a("")
    else:
        a("No capability rows supplied.")
        a("")

    if broken:
        a("### Every broken hunk, stack-wide")
        a("")
        a(
            "The grouping above can only name breaks inside patches that add a "
            "capability literal. This is **all** of them, including the "
            "patches no capability row can reach -- see caveat 2."
        )
        a("")
        a("| Patch | Hunk |")
        a("| --- | --- |")
        for h in broken:
            a(f"| `{h.patch}` | `{h.header.strip()}` |")
        a("")

    a("### CUSTOM_REGROUP -- **GONE**")
    a("")
    a(
        "This is the one genuine seam loss, and the tool above **cannot find "
        "it**. CUSTOM_REGROUP advertises no capability flag, so nothing in "
        "`ADVERTISED_CAPABILITIES` derives it and no row above covers it -- it "
        "is hard-coded into this report precisely so it can never be dropped "
        "by omission. Patches 0001 and 0017 set it via `args['regroup'] = "
        "...`, a dict assignment the capability regex never matches by design."
    )
    a("")
    a(
        "On the branch, `regroup` survives in exactly two places and neither is "
        "a live use: a comment (`# Replaces stable-ts WhisperResult, Segment, "
        "and regroup machinery.`) and the frozenset `_STABLE_TS_KWARGS = "
        "frozenset({'regroup', 'input_sr', 'progress_callback'})`. That "
        "frozenset is a **strip-list**: both transcribe call sites do "
        "`fw_kwargs = {k: v for k, v in kwargs.items() if k not in "
        "_STABLE_TS_KWARGS}` before `**fw_kwargs` reaches faster-whisper. So "
        "`regroup` is not merely unused -- it is **explicitly filtered out**. "
        "Zero live uses. This capability cannot be re-ported at any price and "
        "is the veto candidate."
    )
    a("")

    a("## How to read these numbers")
    a("")
    a(
        "**1. INCONCLUSIVE was NOT counted as breakage, so every count here is "
        "a lower bound on the damage.** A hunk that fails on the pinned base "
        "fails because it depends on text an earlier patch in the stack "
        "creates -- the probe applies each hunk standalone, so it simply "
        "cannot judge those. Scoring them broken would invent damage; scoring "
        "them intact would hide it. They are reported as their own outcome and "
        "excluded from the verdict, which means the true breakage is at least "
        "the `BROKEN_BY_BRANCH` count and possibly more. Resolving them "
        "requires applying the stack cumulatively, which is Phase 2 work."
    )
    a("")
    a(
        "**2. `build_capability_map` under-counts providers, one-directionally.** "
        "It maps a capability to the patches that add its flag literal, so an "
        "implementation patch that never touches the literal is invisible to "
        "it. `runtime_config` maps to `0022` alone even though `0027` and "
        "`0029` also carry its seam. The bias only ever **shrinks** the "
        "evidence set, never inflates it -- so a capability showing breakage "
        "here is real, while a capability showing none may simply have had its "
        "breaking patch left out of the mapping."
    )
    a("")
    a(
        "**3. `SKIPPED_OTHER_FILE` is out of scope, not passing.** Only "
        f"`{PROBED_FILE}` is materialised, because that is the file this branch "
        "refactors. Hunks targeting anything else (`entrypoint.sh`, from "
        "`0021`) are counted and reported rather than dropped, so the "
        "denominator stays honest."
    )
    a("")

    if per_patch:
        a("## Whole-stack census, by patch")
        a("")
        a(
            "Every hunk in `patches/`, including patches that map to no "
            "advertised capability. This is the denominator the per-capability "
            "table above cannot show."
        )
        a("")
        a("| Patch | Hunks | Outcomes |")
        a("| --- | --- | --- |")
        for name in sorted(per_patch):
            counts = per_patch[name]
            a(f"| `{name}` | {sum(counts.values())} | {_counts_cell(counts)} |")
        a("")

    return "\n".join(out)


def _resolve_branch(upstream: Path) -> tuple[str, str]:
    """First of BRANCH_REFS that resolves, as (ref, short sha)."""
    for ref in BRANCH_REFS:
        try:
            sha = _git(upstream, "rev-parse", "--short", ref).decode("ascii").strip()
        except subprocess.CalledProcessError:
            continue
        return ref, sha
    raise SystemExit(
        "none of {} resolve in {}; run:\n"
        "  git -C upstream fetch origin refactor/drop-stable-ts".format(
            ", ".join(BRANCH_REFS), upstream
        )
    )


def main() -> int:
    # Redirected stdout defaults to the console codepage on Windows, and hunk
    # headers can carry non-ASCII -- without this, `> report.md` dies mid-write.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")

    root = Path(__file__).resolve().parent.parent
    upstream = root / "upstream"

    patches = {
        p.name: p.read_text(encoding="utf-8")
        for p in sorted((root / "patches").glob("*.patch"))
    }
    if not patches:
        raise SystemExit(f"no patches found under {root / 'patches'}")

    cap_map = build_capability_map(patches)
    branch_ref, branch_sha = _resolve_branch(upstream)
    base_sha = _git(upstream, "rev-parse", "--short", BASE_REF).decode("ascii").strip()

    results: list[tuple[Hunk, HunkOutcome]] = []
    with tempfile.TemporaryDirectory(prefix="capability-audit-") as td:
        base_tree = Path(td) / "base"
        branch_tree = Path(td) / "branch"
        _materialise(upstream, BASE_REF, base_tree)
        _materialise(upstream, branch_ref, branch_tree)
        for name in sorted(patches):
            for h in hunks_of(name, patches[name]):
                results.append((h, probe_hunk(h, base_tree, branch_tree)))

    per_patch: dict[str, dict[HunkOutcome, int]] = {}
    for h, outcome in results:
        per_patch.setdefault(h.patch, Counter())[outcome] += 1

    rows: list[CapabilityRow] = []
    for cap in sorted(cap_map):
        providers = cap_map[cap]
        counts: Counter[HunkOutcome] = Counter()
        broken: list[str] = []
        for h, outcome in results:
            if h.patch not in providers:
                continue
            counts[outcome] += 1
            if outcome is HunkOutcome.BROKEN_BY_BRANCH:
                broken.append(h.header.strip())
        rows.append((cap, providers, dict(counts), broken))

    print(
        render_report(
            rows,
            branch_sha,
            per_patch={k: dict(v) for k, v in per_patch.items()},
            broken=[h for h, o in results if o is HunkOutcome.BROKEN_BY_BRANCH],
            base_sha=base_sha,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
