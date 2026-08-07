# scripts/capability_audit.py
"""#171: does every capability we depend on have a seam on
refactor/drop-stable-ts?

A patch conflicting is uninteresting -- context drift is routine sync work. A
capability whose SEAM is gone cannot be re-ported at any price, and that is the
veto. See docs/superpowers/specs/2026-08-04-171-drop-stable-ts-evidence-design.md
in the subarr repo.

Two probes answer that, and neither is sufficient alone. The STANDALONE probe
offers each hunk to a pristine tree and asks whether the text it lands on
exists there; it is blind to every hunk whose anchor an earlier patch of OURS
creates, which was 86 of 129 and made the first run a lower bound. The
CUMULATIVE probe applies the whole stack in `patches/series` order against a
mutating tree and asks whether the stack still lands; it sees those anchors but
cannot tell branch deletion from our own upstream break. Cross-tabulated by
`classify_cumulative` they resolve all 129.
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
# The probes. THESE are the verdict; seams_for_patch above is a triage index
# only.
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

# The only upstream file this branch refactors, and so the only one the
# STANDALONE probe judges. patches/0021 also touches entrypoint.sh; asking the
# standalone probe about it would be a category error, so those hunks are
# reported as SKIPPED_OTHER_FILE rather than silently dropped from the
# denominator.
PROBED_FILE = "subgen.py"

# Every file the patch stack touches, and so every file a materialised tree
# must carry. This is deliberately wider than PROBED_FILE: the CUMULATIVE probe
# walks the whole series against one tree, and a tree missing entrypoint.sh
# would fail 0021 on the pinned BASE -- reporting a BASE_ANOMALY that is purely
# an artefact of what we chose to lay down. The base pass must be 129/129, and
# it is only meaningful if every hunk had a file to land on.
MATERIALISED_FILES = (PROBED_FILE, "entrypoint.sh")

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
    CASCADE = "CASCADE"
    INCONCLUSIVE = "INCONCLUSIVE"
    SKIPPED_OTHER_FILE = "SKIPPED_OTHER_FILE"
    BASE_ANOMALY = "BASE_ANOMALY"


# Fixed display order: the decisive outcomes first, then CASCADE (attributable
# to them), then the two the standalone probe alone can produce, then the
# tooling alarm. INCONCLUSIVE and SKIPPED_OTHER_FILE can only ever appear in a
# standalone cell, BASE_ANOMALY and CASCADE only in a resolved one -- one order
# serves both because _counts_cell drops zero counts.
_OUTCOME_ORDER = (
    HunkOutcome.INTACT,
    HunkOutcome.BROKEN_BY_BRANCH,
    HunkOutcome.CASCADE,
    HunkOutcome.INCONCLUSIVE,
    HunkOutcome.SKIPPED_OTHER_FILE,
    HunkOutcome.BASE_ANOMALY,
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


def classify_cumulative(
    standalone_base: bool,
    standalone_branch: bool,
    cumulative_base: bool,
    cumulative_branch: bool,
) -> HunkOutcome:
    """Cross-tabulate both probes into the resolved verdict.

    Neither probe resolves a hunk on its own. The standalone probe is blind to
    every hunk whose anchor an earlier patch of OURS creates -- 86 of 129 on
    the real stack -- because a pristine tree never contains that text. The
    cumulative probe supplies it, but it cannot distinguish "the branch deleted
    this" from "an earlier hunk in our own series failed, so the line I needed
    was never added". Read together they separate exactly that.

    The order of the tests is the meaning, so do not reorder them:

    1. ``cumulative_base`` false is a TOOLING alarm, not a finding. The stack
       applies to the pinned base 129/129 in series order, by construction --
       that is what `patches/` IS. A failure there means the probe stopped
       reproducing the stack, so nothing else in the row is trustworthy and it
       outranks even a decisive-looking standalone break.
    2. Applies standalone to the base but not to the branch is decisive in the
       branch's direction: the hunk lands on real upstream text, and the branch
       no longer has it. Ordering cannot explain that away, so this is checked
       before any cumulative branch result and stays BROKEN_BY_BRANCH even when
       the cumulative pass happens to land it at an offset.
    3. Landing on the branch cumulatively is INTACT -- including the hunks the
       standalone probe could not read, which is the whole point of Phase 2.
    4. Everything left is CASCADE: it did not land, and no probe blames the
       branch for the text it wanted. Its anchor was one of our own added
       lines that an earlier break never got to add. Attributable to that
       break, so counting it as separate damage double-counts one wound.
    """
    if not cumulative_base:
        return HunkOutcome.BASE_ANOMALY
    if standalone_base and not standalone_branch:
        return HunkOutcome.BROKEN_BY_BRANCH
    if cumulative_branch:
        return HunkOutcome.INTACT
    return HunkOutcome.CASCADE


def patches_in_series_order(series_text: str) -> list[str]:
    """Patch filenames in `patches/series` order, comments and blanks dropped.

    File order is the semantics, not an incidental detail: the cumulative probe
    mutates one tree by walking this list, so sorting it would run a different
    experiment. It happens to coincide with sorted() on the current stack --
    the names are zero-padded -- which is exactly why the distinction has to be
    stated rather than left to luck.
    """
    out: list[str] = []
    for line in series_text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            out.append(stripped)
    return out


def _git(repo: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True
    ).stdout


def _materialise(upstream: Path, ref: str, dest: Path) -> None:
    """Lay down a pristine tree of MATERIALISED_FILES at `ref`, then git init it.

    `cat-file blob`, NOT `show`: `show` runs checkout filters (eol conversion,
    smudge), and a CRLF-converted subgen.py would fail every LF hunk in
    patches/ -- yielding an all-INCONCLUSIVE report that reads like a finding
    instead of like the tooling bug it would be.
    """
    dest.mkdir(parents=True, exist_ok=True)
    for name in MATERIALISED_FILES:
        (dest / name).write_bytes(_git(upstream, "cat-file", "blob", f"{ref}:{name}"))
    subprocess.run(["git", "init", "-q"], cwd=dest, check=True, capture_output=True)


def _applies(patch_bytes: bytes, tree: Path, *, mutate: bool = False) -> bool:
    """`git apply` one reconstructed hunk against a materialised tree.

    With `mutate=False` (the standalone probe) this is `--check`: the tree is
    left pristine, so one tree per revision serves all 129 hunks. With
    `mutate=True` (the cumulative probe) the hunk is really applied and the
    tree carries it forward, which is the only way a later hunk can land on
    text an earlier patch of ours added. A failure there is skipped and the
    walk continues -- stopping at the first one would leave every subsequent
    hunk unjudged, and it is precisely those we are here to judge.

    stdin is bytes WE encoded as UTF-8: 19 of the 34 patches carry non-ASCII
    (em-dashes in comments), and letting subprocess encode with the Windows
    console default (cp1252) raises UnicodeEncodeError part-way through a run.

    `git apply` tolerates a line-number OFFSET but not changed context, which is
    exactly the question worth asking: drift is routine, a vanished seam is the
    veto.
    """
    cmd = ["git", "apply", "-"] if mutate else ["git", "apply", "--check", "-"]
    done = subprocess.run(cmd, cwd=tree, input=patch_bytes, capture_output=True)
    return done.returncode == 0


class HunkProbe(NamedTuple):
    """Every `git apply` answer for one hunk: two probes, four trees.

    Field order matches `classify_cumulative`'s parameters on purpose, so the
    call site can splat it and cannot silently transpose a pair.
    """

    standalone_base: bool
    standalone_branch: bool
    cumulative_base: bool
    cumulative_branch: bool


class ProbeTrees(NamedTuple):
    """The four materialised trees one run needs.

    Four, not two: the cumulative pair is mutated hunk by hunk, so it cannot
    double as the pristine pair the standalone probe requires. Sharing them
    would make every standalone answer depend on the hunks already applied,
    which is the exact confound the two probes exist to separate.
    """

    standalone_base: Path
    standalone_branch: Path
    cumulative_base: Path
    cumulative_branch: Path


def probe_hunk(h: Hunk, trees: ProbeTrees) -> HunkProbe:
    """Run both probes for one hunk. MUTATES the two cumulative trees.

    Must be called in `patches/series` order, once per hunk, or the cumulative
    trees stop representing the stack.
    """
    blob = hunk_as_patch(h).encode("utf-8")
    return HunkProbe(
        standalone_base=_applies(blob, trees.standalone_base),
        standalone_branch=_applies(blob, trees.standalone_branch),
        cumulative_base=_applies(blob, trees.cumulative_base, mutate=True),
        cumulative_branch=_applies(blob, trees.cumulative_branch, mutate=True),
    )


def standalone_outcome(h: Hunk, probe: HunkProbe) -> HunkOutcome:
    """The standalone-only verdict, kept so the report can show both probes.

    The resolved verdict comes from `classify_cumulative`; this is the column
    it resolves. Showing only the resolved one would hide how the resolution
    was reached, and showing only this one is the old lower-bound report.
    """
    if h.file != PROBED_FILE:
        return HunkOutcome.SKIPPED_OTHER_FILE
    return classify_hunk(probe.standalone_base, probe.standalone_branch)


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
    resolved_per_patch: dict[str, dict[HunkOutcome, int]] | None = None,
) -> str:
    """Render the audit as markdown.

    `per_patch` is the whole-stack STANDALONE census -- every hunk in patches/,
    including those in patches that map to no advertised capability. It is
    optional because the capability rows are the contract; it is supplied in
    real runs because the per-capability view alone cannot show the
    denominator.

    `resolved_per_patch` is the same census after cross-tabulating both probes,
    and `rows` carry those resolved counts too. Both censuses are rendered side
    by side on purpose: the resolved column alone would assert a verdict
    without showing how it was reached, and the standalone column alone is the
    superseded lower-bound report.

    `broken` is every BROKEN_BY_BRANCH hunk stack-wide, and it is not
    redundant with the per-capability rows: those can only name breaks in
    patches that add a capability literal, which on the real stack is 4 of 11.
    The other 7 -- including the args.update(kwargs) triple, the most
    load-bearing break there is -- would otherwise be invisible. That is
    caveat 2 below biting the report itself.
    """
    per_patch = per_patch or {}
    resolved_per_patch = resolved_per_patch or {}
    total = Counter()
    for counts in per_patch.values():
        total.update(counts)
    resolved_total = Counter()
    for counts in resolved_per_patch.values():
        resolved_total.update(counts)
    n_hunks = sum(total.values()) or sum(resolved_total.values())
    n_patches = len(per_patch) or len(resolved_per_patch)

    out: list[str] = []
    a = out.append

    a("# refactor/drop-stable-ts: capability audit")
    a("")
    a(
        "Generated by `scripts/capability_audit.py`. Every hunk in `patches/` is "
        "offered to a tree at each revision by two probes -- one standalone, one "
        "cumulative -- and judged by whether `git apply` accepts it."
    )
    a("")
    a(f"- **Branch probed**: `refactor/drop-stable-ts` @ `{branch_sha}`")
    if base_sha:
        a(f"- **Pinned base**: `{base_sha}` (the commit `upstream/` sits on)")
    if n_hunks:
        a(f"- **Hunks probed**: {n_hunks} across {n_patches} patches")
    if total:
        a(f"- **Standalone probe**: {_counts_cell(dict(total))}")
    if resolved_total:
        a(f"- **Resolved, both probes**: {_counts_cell(dict(resolved_total))}")
        anomalies = resolved_total[HunkOutcome.BASE_ANOMALY]
        a(
            f"- **Base cumulative pass**: {n_hunks - anomalies}/{n_hunks} applied "
            f"in `patches/series` order (`BASE_ANOMALY` {anomalies})"
        )
    a("")

    a("## Method: two probes, cross-tabulated")
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
    a(
        "**Probe 1, standalone.** Each hunk is reconstructed as a one-hunk "
        "patch and offered to a *pristine* tree at each revision. It answers "
        "one question: does the text this hunk lands on exist in that tree?"
    )
    a("")
    a("| Applies to base | Applies to branch | Reading |")
    a("| --- | --- | --- |")
    a("| yes | yes | the code this hunk lands on still exists |")
    a("| yes | no | decisive: the branch removed it |")
    a(
        "| no | either | unreadable on its own -- the anchor is text an "
        "**earlier patch of ours** creates, which a pristine tree never has |"
    )
    a("")
    a(
        "That last row is the majority of the stack, which is why this probe "
        "alone could only ever report a floor."
    )
    a("")
    a(
        "**Probe 2, cumulative.** A second pair of trees is built and every "
        "hunk is applied **in `patches/series` order**, mutating the tree as it "
        "goes and continuing past failures. It answers a different question: "
        "does the stack still land, in order? It sees the anchors our own "
        "patches create, so it is the only probe that can judge the hunks "
        "probe 1 cannot read -- and it cannot, on its own, tell "
        '"the branch deleted this" from "an earlier hunk of ours never got '
        'to add the line I needed".'
    )
    a("")
    a("Neither probe resolves a hunk alone. Cross-tabulated, they resolve all of them:")
    a("")
    a("| Condition, read top to bottom | Outcome |")
    a("| --- | --- |")
    a(
        "| the cumulative pass fails on the **base** | `BASE_ANOMALY` -- a "
        "tooling alarm, not a finding; see below |"
    )
    a(
        "| standalone: applies to base, not to branch | `BROKEN_BY_BRANCH` -- "
        "decisive, whatever the ordering |"
    )
    a("| the cumulative pass lands it on the **branch** | `INTACT` |")
    a(
        "| anything else | `CASCADE` -- its anchor was ours, and an earlier "
        "break took it |"
    )
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
        a("Outcomes are the **resolved** verdicts -- both probes, cross-tabulated.")
        a("")
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
        "**1. The census is COMPLETE. `BROKEN_BY_BRANCH` is the full count of "
        "independent breaks, and `CASCADE` is attributable to it.** Every hunk "
        "the standalone probe returned `INCONCLUSIVE` on has been resolved by "
        "the cumulative probe, so no hunk is left unjudged and no number here "
        "is a floor. Read the two decisive outcomes like this:"
    )
    a("")
    a(
        "- `BROKEN_BY_BRANCH` is **independent** damage. The hunk applies to "
        "the pinned base and not to the branch, which names upstream code the "
        "branch removed. Nothing about ordering can explain that away, so this "
        "count is the same under both probes."
    )
    a(
        "- `CASCADE` is **attributable** damage, not additional damage. The "
        "hunk failed cumulatively on the branch while no probe blames the "
        "branch for the text it wanted: its anchor was a line one of our own "
        "earlier hunks adds, and that hunk is one of the breaks above. Repair "
        "a `BROKEN_BY_BRANCH` hunk and its cascade comes back within reach; "
        "count the two together and you count one wound twice."
    )
    a(
        "- `INTACT` now includes every hunk the standalone probe could not "
        "read. That is the resolution the cumulative probe was built for, and "
        "it is why the resolved `INTACT` count is far larger than the "
        "standalone one."
    )
    a("")
    a(
        "The invariant that makes all of this readable is the base cumulative "
        "pass in the header: the stack applies to the pinned base in "
        "`patches/series` order with **zero** `BASE_ANOMALY`. That is true by "
        "construction -- it is what `patches/` *is* -- so a nonzero "
        "`BASE_ANOMALY` means the probe stopped reproducing the stack. Treat "
        "it as a tooling alarm and fix the tool before believing any other "
        "number in this report."
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
        "**3. `SKIPPED_OTHER_FILE` is a standalone-probe scope limit, not a "
        f"gap.** The standalone probe judges only `{PROBED_FILE}`, because that "
        "is the file this branch refactors; the hunk targeting `entrypoint.sh` "
        "(from `0021`) is reported as out of scope rather than dropped, so its "
        "denominator stays honest. Both trees nonetheless materialise "
        "`entrypoint.sh` as well -- they must, or that hunk would fail the base "
        "cumulative pass and raise a `BASE_ANOMALY` that says nothing about "
        "either revision -- so the resolved column judges it like any other."
    )
    a("")

    if per_patch or resolved_per_patch:
        a("## Whole-stack census, by patch")
        a("")
        a(
            "Every hunk in `patches/`, including patches that map to no "
            "advertised capability. This is the denominator the per-capability "
            "table above cannot show. Both probes are shown so the "
            "cross-tabulation can be checked patch by patch: read a row as "
            "*what one probe could see* against *what the pair concluded*."
        )
        a("")
        a("| Patch | Hunks | Standalone probe | Resolved |")
        a("| --- | --- | --- | --- |")
        for name in sorted(set(per_patch) | set(resolved_per_patch)):
            counts = per_patch.get(name, {})
            resolved = resolved_per_patch.get(name, {})
            n = sum(counts.values()) or sum(resolved.values())
            standalone_cell = _counts_cell(counts) if counts else "-"
            resolved_cell = _counts_cell(resolved) if resolved else "-"
            a(f"| `{name}` | {n} | {standalone_cell} | {resolved_cell} |")
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


MANUAL_MARKER = "## Manual pass"


def preserve_manual_section(existing_report: str) -> str:
    """The hand-written manual pass from an existing report, or "".

    The probe judges hunks; it cannot judge whether a mechanism has somewhere
    left to attach. That analysis is written by hand under a `## Manual pass`
    heading and is the part of the report that actually decides the veto.

    This audit is explicitly meant to be re-run when the branch moves, and a
    plain `python capability_audit.py > report.md` truncates the file before a
    line of new output is produced -- taking the manual pass with it, silently,
    with a zero exit code. Regeneration reads it back instead.

    Returns the marker heading onwards, so the result is itself preservable and
    a second re-run does not lose what the first one kept.
    """
    idx = existing_report.find(MANUAL_MARKER)
    return existing_report[idx:] if idx != -1 else ""


def main() -> int:
    # Redirected stdout defaults to the console codepage on Windows, and hunk
    # headers can carry non-ASCII -- without this, `> report.md` dies mid-write.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")

    root = Path(__file__).resolve().parent.parent
    upstream = root / "upstream"

    patches_dir = root / "patches"
    patches = {
        p.name: p.read_text(encoding="utf-8")
        for p in sorted(patches_dir.glob("*.patch"))
    }
    if not patches:
        raise SystemExit(f"no patches found under {patches_dir}")

    # The cumulative probe walks `series`, so a mismatch either way is a silent
    # falsifier, not a tidiness issue: a patch file absent from `series` never
    # reaches the tree, and every later hunk needing its added lines then scores
    # CASCADE -- damage manufactured by a bookkeeping slip. Refuse to report.
    order = patches_in_series_order(
        (patches_dir / "series").read_text(encoding="utf-8")
    )
    if set(order) != set(patches):
        raise SystemExit(
            "patches/series does not match patches/*.patch:\n"
            f"  listed but missing on disk: {sorted(set(order) - set(patches))}\n"
            f"  on disk but not in series: {sorted(set(patches) - set(order))}"
        )

    cap_map = build_capability_map(patches)
    branch_ref, branch_sha = _resolve_branch(upstream)
    base_sha = _git(upstream, "rev-parse", "--short", BASE_REF).decode("ascii").strip()

    # (hunk, standalone-only outcome, resolved outcome)
    results: list[tuple[Hunk, HunkOutcome, HunkOutcome]] = []
    with tempfile.TemporaryDirectory(prefix="capability-audit-") as td:
        trees = ProbeTrees(
            standalone_base=Path(td) / "standalone-base",
            standalone_branch=Path(td) / "standalone-branch",
            cumulative_base=Path(td) / "cumulative-base",
            cumulative_branch=Path(td) / "cumulative-branch",
        )
        for ref, tree in (
            (BASE_REF, trees.standalone_base),
            (branch_ref, trees.standalone_branch),
            (BASE_REF, trees.cumulative_base),
            (branch_ref, trees.cumulative_branch),
        ):
            _materialise(upstream, ref, tree)

        # Series order, NOT sorted(patches): the cumulative trees are mutated in
        # this order, so it is the experiment. The two coincide on the current
        # stack because the filenames are zero-padded, which is exactly why the
        # authoritative list has to be the one that is read from disk.
        for name in order:
            for h in hunks_of(name, patches[name]):
                probe = probe_hunk(h, trees)
                # HunkProbe's field order matches classify_cumulative's
                # parameters, so splatting cannot transpose a pair.
                results.append(
                    (h, standalone_outcome(h, probe), classify_cumulative(*probe))
                )

    per_patch: dict[str, dict[HunkOutcome, int]] = {}
    resolved_per_patch: dict[str, dict[HunkOutcome, int]] = {}
    for h, standalone, resolved in results:
        per_patch.setdefault(h.patch, Counter())[standalone] += 1
        resolved_per_patch.setdefault(h.patch, Counter())[resolved] += 1

    rows: list[CapabilityRow] = []
    for cap in sorted(cap_map):
        providers = cap_map[cap]
        counts: Counter[HunkOutcome] = Counter()
        broken: list[str] = []
        for h, _standalone, resolved in results:
            if h.patch not in providers:
                continue
            counts[resolved] += 1
            if resolved is HunkOutcome.BROKEN_BY_BRANCH:
                broken.append(h.header.strip())
        rows.append((cap, providers, dict(counts), broken))

    report = render_report(
        rows,
        branch_sha,
        per_patch={k: dict(v) for k, v in per_patch.items()},
        broken=[h for h, _s, r in results if r is HunkOutcome.BROKEN_BY_BRANCH],
        base_sha=base_sha,
        resolved_per_patch={k: dict(v) for k, v in resolved_per_patch.items()},
    )

    # Writing the file ourselves, rather than leaving it to a `> report.md`
    # redirect, is the whole point: the redirect truncates before we run and
    # would take the hand-written manual pass with it.
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if out_path is None:
        print(report)
        return 0

    manual = ""
    if out_path.exists():
        manual = preserve_manual_section(out_path.read_text(encoding="utf-8"))
    # newline="\n" is not cosmetic. Without it, write_text translates to the
    # platform ending, so regenerating on Windows rewrites every line of the
    # file as CRLF against an LF-committed file. Every re-run would then diff
    # as a total rewrite, burying the one line that actually changed -- and
    # this audit exists to be re-run when the branch moves.
    out_path.write_text(
        report + ("\n" + manual if manual else ""), encoding="utf-8", newline="\n"
    )
    kept = (
        f", preserved {manual.count(chr(10)) + 1} lines of manual pass"
        if manual
        else ""
    )
    print(f"wrote {out_path}{kept}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
