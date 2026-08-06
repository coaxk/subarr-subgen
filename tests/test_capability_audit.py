# tests/test_capability_audit.py
from pathlib import Path

from scripts.capability_audit import (
    ADVERTISED_CAPABILITIES,
    build_capability_map,
    capabilities_added_by_patch,
)

PATCHES_DIR = Path(__file__).resolve().parent.parent / "patches"

PATCH_WITH_CONTEXT = """--- a/subgen.py
+++ b/subgen.py
@@ -580,6 +580,7 @@ def queue_status():
             "capabilities": {
                 "audio_language_override": True,
+                "queue_cancel": True,
             },
"""


def test_only_added_lines_count():
    # audio_language_override is CONTEXT here, not provided by this patch.
    assert capabilities_added_by_patch(PATCH_WITH_CONTEXT) == {"queue_cancel"}


def test_patch_with_no_capabilities_returns_empty():
    assert capabilities_added_by_patch("--- a/x\n+++ b/x\n+print('hi')\n") == set()


def test_non_boolean_capability_values_still_count():
    # concurrent_transcriptions is an int, not True.
    body = '--- a/s\n+++ b/s\n+            "concurrent_transcriptions": concurrent_transcriptions,\n'
    assert capabilities_added_by_patch(body) == {"concurrent_transcriptions"}


def test_removal_lines_are_ignored():
    body = '--- a/s\n+++ b/s\n-                "old_flag": True,\n'
    assert capabilities_added_by_patch(body) == set()


def test_multiple_capabilities_on_one_line():
    # Regression test: patches/0029-async-config-switch.patch has an added line
    # with two keys -- "state" and "model" -- and a naive .search() only ever
    # returns the first, silently dropping the second.
    body = '--- a/s\n+++ b/s\n+    "ignore_forced_subtitles": True, "runtime_config": True,\n'
    assert capabilities_added_by_patch(body) == {
        "ignore_forced_subtitles",
        "runtime_config",
    }


def test_capabilities_accumulate_across_lines():
    # Every other test in this file produces a set of size <= 1, which does not
    # prove the set actually grows across multiple added lines.
    body = (
        "--- a/s\n+++ b/s\n"
        '+            "detect_language_track": True,\n'
        '+            "audio_language_override": True,\n'
    )
    assert capabilities_added_by_patch(body) == {
        "detect_language_track",
        "audio_language_override",
    }


def test_advertised_list_is_the_sixteen_live_flags():
    assert len(ADVERTISED_CAPABILITIES) == 16
    assert "per_request_kwargs" in ADVERTISED_CAPABILITIES
    assert "asr_arena" in ADVERTISED_CAPABILITIES
    assert "runtime_config" in ADVERTISED_CAPABILITIES
    # Response fields must NOT be treated as capabilities.
    assert "queued_count" not in ADVERTISED_CAPABILITIES
    assert "ok" not in ADVERTISED_CAPABILITIES


def test_map_drops_non_capability_keys():
    patches = {
        "0007-queue.patch": '+                "queued_count": len(q),\n',
        "0010-queue-cancel.patch": '+                "queue_cancel": True,\n',
    }
    m = build_capability_map(patches)
    assert m == {"queue_cancel": ["0010-queue-cancel.patch"]}


def test_map_records_every_provider_for_a_capability():
    # b.patch is listed first here on purpose: build_capability_map must sort
    # its own output, not merely preserve whatever order the caller passed in.
    patches = {
        "b.patch": '+                "runtime_config": True,\n',
        "a.patch": '+                "runtime_config": True,\n',
    }
    assert build_capability_map(patches)["runtime_config"] == ["a.patch", "b.patch"]


def test_every_advertised_capability_is_provided_by_a_real_patch():
    # Guards against DRIFT: if a future patch renames or drops one of the 16
    # literals, capabilities_added_by_patch stops finding it and
    # build_capability_map silently omits it -- indistinguishable downstream
    # from "never provided". This must fail loudly, not pass vacuously, so it
    # asserts the patch list is non-empty before the subset check.
    patch_files = sorted(PATCHES_DIR.glob("*.patch"))
    assert patch_files, f"no patch files found under {PATCHES_DIR}"

    provided: set[str] = set()
    for path in patch_files:
        provided |= capabilities_added_by_patch(
            path.read_text(encoding="utf-8", errors="replace")
        )

    missing = ADVERTISED_CAPABILITIES - provided
    assert not missing, (
        f"advertised capabilities with no patch provider: {sorted(missing)}"
    )
