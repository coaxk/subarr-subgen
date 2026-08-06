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

# Matches a capability entry in the /queue capabilities dict. The value may be
# True, an int, or an expression -- concurrent_transcriptions is an int -- so the
# value side is deliberately not constrained.
_CAP_ENTRY = re.compile(r'"(?P<name>[a-z][a-z0-9_]*)"\s*:')


def capabilities_added_by_patch(patch_text: str) -> set[str]:
    """Capability names this patch ADDS.

    Only `+` lines count. Patch context lines show neighbouring flags, and
    attributing those to the patch credits the wrong one -- verified during
    planning, where a naive scan credited 0010-queue-cancel with
    audio_language_override, which it merely sits below.
    """
    found: set[str] = set()
    for line in patch_text.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        m = _CAP_ENTRY.search(line)
        if m:
            found.add(m.group("name"))
    return found
