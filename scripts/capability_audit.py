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
